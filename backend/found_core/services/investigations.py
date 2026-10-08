"""Starting provenance runs (design Sections 5.2 step 2, 6.6 and 9.8).

Every control decision about paid, model-driven work is made here, in a fixed order:
fingerprint, cache, live switch, run lock, budget, then queue. A cached result costs
nothing. A live run needs the switch on, a free lock and a reserved budget slot, and the
slot is never given back, so a run that later fails still counts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from found_core.domain.auth import ADMIN, REVIEWER, Caller
from found_core.domain.enums import InvestigationMode, InvestigationStatus
from found_core.domain.errors import (
    BudgetLimit,
    Forbidden,
    InProgress,
    LiveUnavailable,
    NotFound,
    ServiceUnavailable,
)
from found_core.domain.ids import new_id
from found_core.domain.investigation import (
    InvestigationConfig,
    budget_period,
    can_transition,
    fingerprint,
)
from found_core.domain.models import Claim, Investigation, Settings
from found_core.ports.budget import BudgetLedger
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.queue import InvestigationQueue
from found_core.ports.repository import FoundRepository

SETTINGS_TTL = timedelta(seconds=15)


@dataclass(frozen=True)
class StartResult:
    investigation: Investigation
    mode: InvestigationMode
    created: bool


class InvestigationService:
    def __init__(
        self,
        repo: FoundRepository,
        ledger: BudgetLedger,
        queue: InvestigationQueue,
        config: InvestigationConfig,
        clock: Clock | None = None,
    ) -> None:
        self._repo = repo
        self._ledger = ledger
        self._queue = queue
        self._config = config
        self._clock = clock or SystemClock()
        self._settings: tuple[datetime, Settings] | None = None

    def fingerprint_for(self, claim: Claim) -> str:
        mentioned = list(claim.mentioned_source_ids)
        latest = {sid: self._repo.latest_source_claim_id(sid) for sid in set(mentioned)}
        return fingerprint(claim, mentioned, latest, self._config)

    def start(self, caller: Caller, claim_id: str, *, force_live: bool = False) -> StartResult:
        if not (caller.has(REVIEWER) or caller.has(ADMIN)):
            raise Forbidden("Only reviewers can start investigations.")
        if force_live and not caller.has(ADMIN):
            raise Forbidden("Only admins can skip the stored result.")
        claim = self._repo.get_claim(claim_id)
        if claim is None:
            raise NotFound("Claim not found.", claim_id=claim_id)

        fp = self.fingerprint_for(claim)
        if not force_live:
            cached = self._repo.find_cached_investigation(fp)
            if cached is not None:
                return StartResult(cached, InvestigationMode.CACHED, created=False)

        settings = self._current_settings()
        if not settings.live_enabled:
            raise LiveUnavailable("Live investigations are switched off.")

        now = self._clock.now()
        investigation_id = new_id("inv")
        holder = self._repo.acquire_run_lock(
            claim.id, investigation_id, now, now + self._config.lock_ttl
        )
        if holder != investigation_id:
            raise InProgress(
                "An investigation of this claim is already running.", investigation_id=holder
            )

        period = budget_period(now)
        cap = settings.run_cap if settings.run_cap is not None else self._config.run_cap
        if not self._ledger.reserve_run(period, cap):
            self._repo.release_run_lock(claim.id, investigation_id)
            raise BudgetLimit(
                "The monthly investigation budget is used up.", period=period, cap=cap
            )

        investigation = Investigation(
            id=investigation_id,
            incident_id=claim.incident_id,
            claim_id=claim.id,
            fingerprint=fp,
            mode=InvestigationMode.LIVE,
            status=InvestigationStatus.QUEUED,
            model_id=self._config.model_id,
            prompt_version=self._config.prompt_version,
            agent_version=self._config.agent_version,
            created_by=caller.user_id,
            queued_at=now,
        )
        try:
            self._repo.put_investigation(investigation)
        except Exception:
            self._repo.release_run_lock(claim.id, investigation_id)
            raise
        try:
            self._queue.send(investigation_id)
        except Exception as err:
            failed = self._fail_queued(investigation, "QUEUE_UNAVAILABLE")
            self._repo.release_run_lock(claim.id, investigation_id)
            raise ServiceUnavailable(
                "The investigation could not be queued.",
                investigation_id=(failed or investigation).id,
            ) from err
        return StartResult(investigation, InvestigationMode.LIVE, created=True)

    def _fail_queued(self, investigation: Investigation, reason: str) -> Investigation | None:
        target = InvestigationStatus.FAILED
        if not can_transition(investigation.status, target):
            return None
        return self._repo.update_investigation_if(
            investigation.id,
            investigation.status,
            {"status": target, "failure_reason": reason, "finished_at": self._clock.now()},
        )

    def _current_settings(self) -> Settings:
        now = self._clock.now()
        if self._settings is not None and now - self._settings[0] < SETTINGS_TTL:
            return self._settings[1]
        settings = self._repo.get_settings()
        self._settings = (now, settings)
        return settings
