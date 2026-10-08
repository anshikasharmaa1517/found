"""Demo reset and recorded runs (design Sections 5.5, UC-6, FR-24, FR-32 and FR-33).

A reset removes only the demo incident's items, reloads the fixtures through ingest
and restores recorded runs as REPLAYED. Budget, settings and other incidents stay as
they are. Activity entries say when the reset started and what it restored.

Recorded runs come only from real, finished investigations (product rule 7): an admin
exports one with `recording`, and it is kept in `runs.json`. Ids change on every load,
so a recording names reports, sources and people by stable keys instead.
"""

import re
from dataclasses import dataclass
from typing import Any

from found_core.domain.auth import ADMIN, Caller
from found_core.domain.enums import InvestigationMode, InvestigationStatus, ReviewItemType
from found_core.domain.errors import BadRequest, Forbidden, NotFound
from found_core.domain.findings import review_priority
from found_core.domain.ids import new_id, review_item_id
from found_core.domain.investigation import CACHEABLE_STATUSES, InvestigationConfig, fingerprint
from found_core.domain.models import (
    Activity,
    Citation,
    Claim,
    Investigation,
    InvestigationStep,
    ReviewItem,
)
from found_core.fixtures import Dataset, LoadResult, load_dataset, reference_key
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.fixtures import FixtureSource, ResetTrigger
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read
from found_core.services.ingest import IngestService

COMPONENT = "admin"
ACTIVITY_MAX = 100
_PLACEHOLDER = re.compile(r"\{(claim|source|subject):([^{}]+)\}")


@dataclass(frozen=True)
class ResetResult:
    incident_id: str
    removed: int
    published: int
    replayed_runs: int


def _require_admin(caller: Caller) -> None:
    if not caller.has(ADMIN):
        raise Forbidden("Only admins can do this.")


class _Ids:
    """Old ids to stable keys when recording; stable keys to new ids when replaying."""

    def __init__(self, to_key: dict[str, str]) -> None:
        self.to_key = to_key

    def hide(self, text: str | None) -> str | None:
        if text is None:
            return None
        # Longest first, so no id is replaced inside a longer one.
        for old in sorted(self.to_key, key=len, reverse=True):
            text = text.replace(old, self.to_key[old])
        return text


class DemoService:
    def __init__(
        self,
        repo: FoundRepository,
        ingest: IngestService,
        fixtures: FixtureSource,
        trigger: ResetTrigger | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repo = repo
        self._ingest = ingest
        self._fixtures = fixtures
        self._trigger = trigger
        self._clock = clock or SystemClock()

    def _dataset(self) -> Dataset:
        return Dataset.from_files(self._fixtures.read())

    def _activity(self, incident_id: str, actor: str, message: str, targets=()) -> None:
        self._repo.put_activity(
            Activity(
                id=new_id("act"),
                incident_id=incident_id,
                actor=actor,
                component=COMPONENT,
                message=message,
                target_ids=tuple(targets),
                created_at=self._clock.now(),
            )
        )

    def _check_resettable(self, incident_id: str) -> Dataset:
        dataset = self._dataset()
        if dataset.incident.id != incident_id or not dataset.incident.is_demo:
            raise BadRequest("Only the demo incident can be reset.", incident_id=incident_id)
        incident = self._repo.get_incident(incident_id)
        if incident is not None and not incident.is_demo:
            raise BadRequest("This incident is not a demo incident.", incident_id=incident_id)
        return dataset

    def request_reset(self, caller: Caller, incident_id: str) -> None:
        """Checked in the API, done by the reset worker, which can take longer."""
        _require_admin(caller)
        self._check_resettable(incident_id)
        if self._trigger is None:
            raise BadRequest("Reset is not available here.")
        if self._repo.incident_exists(incident_id):
            self._activity(incident_id, caller.user_id, "Demo reset requested")
        self._trigger.start(incident_id, caller.user_id)

    def reset(self, incident_id: str, actor: str) -> ResetResult:
        dataset = self._check_resettable(incident_id)
        removed = self._repo.delete_incident_data(incident_id)
        loaded = load_dataset(dataset, self._repo, self._ingest)
        runs = [self._replay(run, loaded) for run in dataset.runs]
        self._activity(
            incident_id,
            actor,
            f"Demo reset: {loaded.published} reports loaded, {len(runs)} recorded runs "
            f"restored as REPLAYED",
            runs,
        )
        return ResetResult(incident_id, removed, loaded.published, len(runs))

    def activity(self, caller: Caller, incident_id: str, limit: int = 50) -> list[Activity]:
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)
        return self._repo.list_activity(incident_id, min(limit, ACTIVITY_MAX))

    # Recording and replay.

    def _keys(self, incident_id: str) -> dict[str, str]:
        sources = {s.id: s for s in self._repo.list_sources(incident_id)}
        keys: dict[str, str] = {}
        # A person is named by their first report (seq 1), the same on every load.
        claims = sorted(self._repo.list_incident_claims(incident_id), key=lambda c: c.seq)
        for claim in claims:
            source = sources.get(claim.source_id)
            if source is None or not source.organization_id:
                continue
            ref = reference_key(source.organization_id, claim.external_reference)
            keys[claim.id] = f"{{claim:{ref}}}"
            keys.setdefault(claim.subject_id, f"{{subject:{ref}}}")
        for source in sources.values():
            keys[source.id] = f"{{source:{source.name}}}"
        return keys

    def recording(self, caller: Caller, investigation_id: str) -> dict[str, Any]:
        """A finished real run in the `runs.json` format."""
        _require_admin(caller)
        inv = self._repo.get_investigation(investigation_id)
        if inv is None:
            raise NotFound("Investigation not found.", investigation_id=investigation_id)
        if inv.mode != InvestigationMode.LIVE or inv.status not in CACHEABLE_STATUSES:
            raise BadRequest("Only a finished live run with a finding can be recorded.")
        ids = _Ids(self._keys(inv.incident_id))
        data = inv.model_dump(mode="json")
        return {
            "claim": ids.hide(inv.claim_id),
            "referenced_source": ids.hide(inv.referenced_source_id),
            "citations": [
                {"claim": ids.hide(c.claim_id), "excerpt": c.excerpt} for c in inv.citations
            ],
            **{
                k: data[k]
                for k in (
                    "model_id",
                    "prompt_version",
                    "agent_version",
                    "status",
                    "attribution",
                    "comparison",
                    "summary",
                    "outcome_reasons",
                    "tool_calls",
                    "model_calls",
                    "input_tokens",
                    "output_tokens",
                    "usage_source",
                    "queued_at",
                    "started_at",
                    "finished_at",
                )
            },  # fmt: skip
            "steps": [
                {
                    "seq": s.seq,
                    "kind": s.kind.value,
                    "tool_name": s.tool_name,
                    "input_json": ids.hide(s.input_json),
                    "output_summary": ids.hide(s.output_summary),
                    "duration_ms": s.duration_ms,
                    "input_tokens": s.input_tokens,
                    "output_tokens": s.output_tokens,
                    "error_code": s.error_code,
                }
                for s in self._repo.list_investigation_steps(inv.id)
            ],
        }

    def _replay(self, run: dict[str, Any], loaded: LoadResult) -> str:
        incident_id = next(iter(loaded.claims_by_reference.values())).incident_id
        sources = {s.name: s.id for s in self._repo.list_sources(incident_id)}
        subject_of = {ref: c.subject_id for ref, c in loaded.claims_by_reference.items()}

        def resolve(match: re.Match[str]) -> str:
            kind, key = match.groups()
            if kind == "claim":
                return loaded.claims_by_reference[key].id
            if kind == "subject":
                return subject_of[key]
            return sources[key]

        def show(text: str | None) -> str | None:
            return None if text is None else _PLACEHOLDER.sub(resolve, text)

        claim = _claim(loaded, show(run["claim"]))
        config = InvestigationConfig(
            model_id=run["model_id"],
            prompt_version=run["prompt_version"],
            agent_version=run["agent_version"],
        )
        mentioned = list(claim.mentioned_source_ids)
        latest = {sid: self._repo.latest_source_claim_id(sid) for sid in set(mentioned)}
        investigation = Investigation(
            id=new_id("inv"),
            incident_id=claim.incident_id,
            claim_id=claim.id,
            fingerprint=fingerprint(claim, mentioned, latest, config),
            mode=InvestigationMode.REPLAYED,
            status=run["status"],
            model_id=run["model_id"],
            prompt_version=run["prompt_version"],
            agent_version=run["agent_version"],
            attribution=run.get("attribution"),
            referenced_source_id=show(run.get("referenced_source")),
            comparison=run.get("comparison"),
            summary=run.get("summary"),
            citations=tuple(
                Citation(claim_id=show(c["claim"]), excerpt=c["excerpt"])
                for c in run.get("citations", ())
            ),
            outcome_reasons=tuple(run.get("outcome_reasons", ())),
            tool_calls=run.get("tool_calls", 0),
            model_calls=run.get("model_calls", 0),
            input_tokens=run.get("input_tokens"),
            output_tokens=run.get("output_tokens"),
            usage_source=run.get("usage_source"),
            created_by="demo-loader",
            # The original run's times: a replay never claims to have run now.
            queued_at=run["queued_at"],
            started_at=run.get("started_at"),
            finished_at=run.get("finished_at"),
        )
        self._repo.put_investigation(investigation)
        for step in run.get("steps", ()):
            self._repo.put_investigation_step(
                InvestigationStep(
                    investigation_id=investigation.id,
                    incident_id=investigation.incident_id,
                    seq=step["seq"],
                    kind=step["kind"],
                    tool_name=step.get("tool_name"),
                    input_json=show(step.get("input_json")),
                    output_summary=show(step.get("output_summary")),
                    duration_ms=step.get("duration_ms"),
                    input_tokens=step.get("input_tokens"),
                    output_tokens=step.get("output_tokens"),
                    error_code=step.get("error_code"),
                    created_at=investigation.finished_at or investigation.queued_at,
                )
            )
        priority = review_priority(investigation.outcome_reasons)
        if investigation.status == InvestigationStatus.NEEDS_REVIEW and priority is not None:
            self._repo.put_review_item_if_absent(
                ReviewItem(
                    id=review_item_id(ReviewItemType.FINDING, investigation.id),
                    incident_id=investigation.incident_id,
                    item_type=ReviewItemType.FINDING,
                    ref_id=investigation.id,
                    subject_id=claim.subject_id,
                    priority=priority,
                    created_at=self._clock.now(),
                )
            )
        return investigation.id


def _claim(loaded: LoadResult, claim_id: str | None) -> Claim:
    for claim in loaded.claims_by_reference.values():
        if claim.id == claim_id:
            return claim
    raise BadRequest("A recorded run names a report that is not in the dataset.")
