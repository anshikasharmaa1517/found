from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import InvestigationMode, InvestigationStatus
from found_core.domain.errors import (
    BudgetLimit,
    Forbidden,
    InProgress,
    LiveUnavailable,
    NotFound,
    ServiceUnavailable,
)
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import Settings
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
ADMIN = Caller(user_id="adm_1", groups=frozenset({"admin"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))

HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}


class FixedClock:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail = False

    def send(self, investigation_id: str) -> None:
        if self.fail:
            raise RuntimeError("queue down")
        self.sent.append(investigation_id)


class World:
    def __init__(self, run_cap: int = 200) -> None:
        self.clock = FixedClock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.settings = Settings(live_enabled=True)
        self.ledger = InMemoryBudgetLedger()
        self.queue = FakeQueue()
        self.ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.config = InvestigationConfig(model_id="model-a", run_cap=run_cap)
        self.service = self.make_service()
        self.refs = 0
        self.source_claim = self.publish(HOSPITAL, "Maya Rawat admitted to ward 3, stable.")
        self.relay = self.publish(
            NGO, "According to Central Hospital Demo, Maya R. was admitted.", self.source_claim
        )

    def make_service(self):
        return InvestigationService(
            self.repo, self.ledger, self.queue, self.config, clock=self.clock
        )

    def publish(self, org, text, about=None):
        self.refs += 1
        subject = (
            {"type": "PERSON", "id": about.subject_id}
            if about
            else {"type": "PERSON", "new": {"name": "Maya Rawat"}}
        )
        return self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": "FOUND_SAFE",
                    "original_text": text,
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": f"2026-10-05T0{self.refs}:00:00Z",
                }
            )
        ).claim

    def finish(self, investigation_id, status=InvestigationStatus.NEEDS_REVIEW):
        S = InvestigationStatus
        self.repo.update_investigation_if(investigation_id, S.QUEUED, {"status": S.RUNNING})
        self.repo.update_investigation_if(
            investigation_id, S.RUNNING, {"status": status, "finished_at": self.clock.now()}
        )
        self.repo.release_run_lock(self.relay.id, investigation_id)


@pytest.fixture
def world():
    return World()


def test_start_queues_a_live_run(world):
    result = world.service.start(REVIEWER, world.relay.id)
    inv = result.investigation
    assert result.created and result.mode == InvestigationMode.LIVE
    assert inv.status == InvestigationStatus.QUEUED and inv.mode == InvestigationMode.LIVE
    assert inv.claim_id == world.relay.id and inv.incident_id == "inc_1"
    assert (inv.model_id, inv.prompt_version) == ("model-a", "lineage-v1")
    assert inv.created_by == "rev_1" and inv.queued_at == world.clock.at
    assert inv.fingerprint == world.service.fingerprint_for(world.relay)
    assert world.repo.get_investigation(inv.id) == inv
    assert world.queue.sent == [inv.id]
    assert world.ledger.usage("2026-10").runs == 1


def test_same_evidence_is_served_cached_without_a_new_run(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    world.finish(first.id)
    again = world.service.start(REVIEWER, world.relay.id)
    assert again.mode == InvestigationMode.CACHED and not again.created
    assert again.investigation.id == first.id
    assert world.queue.sent == [first.id]
    assert world.ledger.usage("2026-10").runs == 1


def test_cache_does_not_need_the_live_switch(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    world.finish(first.id, InvestigationStatus.COMPLETED)
    world.repo.settings = Settings(live_enabled=False)
    world.clock.at += timedelta(minutes=1)
    assert world.service.start(REVIEWER, world.relay.id).mode == InvestigationMode.CACHED


def test_failed_runs_are_never_served_from_cache(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    world.finish(first.id, InvestigationStatus.FAILED)
    again = world.service.start(REVIEWER, world.relay.id)
    assert again.mode == InvestigationMode.LIVE and again.investigation.id != first.id


def test_new_claim_from_the_mentioned_source_forces_a_fresh_run(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    world.finish(first.id)
    world.publish(HOSPITAL, "Maya Rawat moved to ward 5.", world.source_claim)
    again = world.service.start(REVIEWER, world.relay.id)
    assert again.mode == InvestigationMode.LIVE
    assert again.investigation.fingerprint != first.fingerprint


def test_admin_force_live_skips_the_cache(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    world.finish(first.id)
    forced = world.service.start(ADMIN, world.relay.id, force_live=True)
    assert forced.mode == InvestigationMode.LIVE and forced.investigation.id != first.id


def test_force_live_is_admin_only(world):
    with pytest.raises(Forbidden):
        world.service.start(REVIEWER, world.relay.id, force_live=True)


@pytest.mark.parametrize("caller", [FAMILY, Caller(user_id="p", groups=frozenset({"publisher"}))])
def test_only_reviewers_and_admins_start_runs(world, caller):
    with pytest.raises(Forbidden):
        world.service.start(caller, world.relay.id)
    assert world.queue.sent == []


def test_unknown_claim_is_not_found(world):
    with pytest.raises(NotFound):
        world.service.start(REVIEWER, "clm_missing")


def test_live_switch_off_is_503_and_spends_nothing(world):
    world.repo.settings = Settings(live_enabled=False)
    with pytest.raises(LiveUnavailable):
        world.service.start(REVIEWER, world.relay.id)
    assert world.ledger.usage("2026-10").runs == 0
    assert world.repo.run_locks == {}


def test_settings_are_reread_after_15_seconds(world):
    world.service.start(REVIEWER, world.source_claim.id)
    world.repo.settings = Settings(live_enabled=False)
    world.clock.at += timedelta(seconds=14)
    world.service.start(REVIEWER, world.relay.id)
    world.clock.at += timedelta(seconds=2)
    with pytest.raises(LiveUnavailable):
        world.service.start(ADMIN, world.relay.id, force_live=True)


def test_second_start_while_running_is_409_with_the_holder(world):
    first = world.service.start(REVIEWER, world.relay.id).investigation
    with pytest.raises(InProgress) as err:
        world.service.start(REVIEWER, world.relay.id)
    assert err.value.details == {"investigation_id": first.id}
    assert world.ledger.usage("2026-10").runs == 1


def test_expired_lock_is_taken_over(world):
    world.service.start(REVIEWER, world.relay.id)
    world.clock.at += timedelta(minutes=10)
    assert world.service.start(REVIEWER, world.relay.id).created


def test_parallel_starts_queue_exactly_one_run(world):
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: _try_start(world), range(8)))
    assert outcomes.count("queued") == 1 and outcomes.count("in_progress") == 7
    assert len(world.queue.sent) == 1


def _try_start(world):
    try:
        world.service.start(REVIEWER, world.relay.id)
        return "queued"
    except InProgress:
        return "in_progress"


def test_budget_cap_is_429_and_frees_the_lock():
    world = World(run_cap=1)
    world.service.start(REVIEWER, world.source_claim.id)
    with pytest.raises(BudgetLimit) as err:
        world.service.start(REVIEWER, world.relay.id)
    assert err.value.details == {"period": "2026-10", "cap": 1}
    assert world.relay.id not in world.repo.run_locks
    assert world.ledger.usage("2026-10").runs == 1


def test_settings_cap_overrides_the_configured_cap(world):
    world.repo.settings = Settings(live_enabled=True, run_cap=0)
    with pytest.raises(BudgetLimit) as err:
        world.service.start(REVIEWER, world.relay.id)
    assert err.value.details["cap"] == 0


def test_budget_is_per_month(world):
    world.config = InvestigationConfig(model_id="model-a", run_cap=1)
    world.service = world.make_service()
    world.service.start(REVIEWER, world.relay.id)
    world.clock.at = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    world.service.start(REVIEWER, world.source_claim.id)
    assert world.ledger.usage("2026-10").runs == 1
    assert world.ledger.usage("2026-11").runs == 1


def test_queue_failure_marks_the_run_failed_and_keeps_the_budget_spent(world):
    world.queue.fail = True
    with pytest.raises(ServiceUnavailable) as err:
        world.service.start(REVIEWER, world.relay.id)
    inv = world.repo.get_investigation(err.value.details["investigation_id"])
    assert inv.status == InvestigationStatus.FAILED
    assert inv.failure_reason == "QUEUE_UNAVAILABLE" and inv.finished_at == world.clock.at
    assert world.relay.id not in world.repo.run_locks
    assert world.ledger.usage("2026-10").runs == 1
    assert world.repo.find_cached_investigation(inv.fingerprint) is None
