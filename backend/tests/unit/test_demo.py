from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from found_core.adapters.fixtures import DirectoryFixtures
from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.enums import InvestigationMode, ReviewItemType, StepKind
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.errors import BadRequest, Forbidden, NotFound
from found_core.domain.findings import quotes
from found_core.domain.ids import review_item_id
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import Incident, InvestigationStep, Settings, Subscription
from found_core.fixtures import reference_key
from found_core.services.demo import DemoService
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService
from found_core.tools.service import AgentToolService

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "demo-v1"
ADMIN = Caller(user_id="adm_1", groups=frozenset({"admin"}))
REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
CONFIG = InvestigationConfig(model_id="model-a")


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


class Trigger:
    def __init__(self):
        self.started = []

    def start(self, incident_id, actor):
        self.started.append((incident_id, actor))


class Queue:
    def send(self, investigation_id):
        pass


class WithRuns:
    """The committed fixtures plus recorded runs."""

    def __init__(self, runs):
        self.runs = runs

    def read(self):
        files = DirectoryFixtures(FIXTURES).read()
        return {**files, "runs.json": self.runs}


class World:
    def __init__(self, fixtures=None):
        self.clock = Clock()
        self.repo = InMemoryFoundRepository()
        self.repo.settings = Settings(live_enabled=True)
        self.ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.trigger = Trigger()
        self.demo = DemoService(
            self.repo,
            self.ingest,
            fixtures or DirectoryFixtures(FIXTURES),
            self.trigger,
            clock=self.clock,
        )

    def claim(self, org, ref):
        source = next(s for s in self.repo.list_sources("inc_demo") if s.organization_id == org)
        return next(
            c
            for c in self.repo.list_incident_claims("inc_demo")
            if c.source_id == source.id and c.external_reference == ref
        )


@pytest.fixture
def world():
    w = World()
    w.demo.reset("inc_demo", "adm_1")
    return w


def test_reset_loads_the_demo_and_logs_it(world):
    assert world.repo.get_incident("inc_demo").is_demo
    assert len(world.repo.list_incident_claims("inc_demo")) == 66
    (entry,) = world.repo.list_activity("inc_demo", 10)
    assert entry.component == "admin" and entry.actor == "adm_1"
    assert entry.message == "Demo reset: 66 reports loaded, 0 recorded runs restored as REPLAYED"


def test_reset_removes_demo_changes_and_keeps_everything_else(world):
    repo = world.repo
    maya = world.claim("org_police", "DPD-0001").subject_id
    repo.add_subscription(Subscription(id="sub_1", subject_id=maya, user_id="fam_1"))
    repo.add_incident("inc_other")
    repo.settings = Settings(live_enabled=True, run_cap=7)
    starter = InvestigationService(repo, InMemoryBudgetLedger(), Queue(), CONFIG, world.clock)
    inv = starter.start(REVIEWER, world.claim("org_ngo", "FRD-0001").id).investigation
    before = {c.id for c in repo.list_incident_claims("inc_demo")}

    world.clock.at += timedelta(hours=1)
    result = world.demo.reset("inc_demo", "adm_2")
    assert result.removed > 66 and result.published == 66
    after = {c.id for c in repo.list_incident_claims("inc_demo")}
    assert len(after) == 66 and not (before & after)
    assert repo.subscriptions == {} and repo.get_investigation(inv.id) is None
    assert repo.run_locks == {}
    assert repo.incident_exists("inc_other")
    assert repo.settings == Settings(live_enabled=True, run_cap=7)
    # The earlier log went with the incident; the new reset is logged.
    assert [a.actor for a in repo.list_activity("inc_demo", 10)] == ["adm_2"]


def test_a_run_still_going_cannot_write_after_a_reset(world):
    repo = world.repo
    starter = InvestigationService(repo, InMemoryBudgetLedger(), Queue(), CONFIG, world.clock)
    inv = starter.start(REVIEWER, world.claim("org_ngo", "FRD-0001").id).investigation
    repo.update_investigation_if(inv.id, S.QUEUED, {"status": S.RUNNING})
    world.demo.reset("inc_demo", "adm_1")
    tools = AgentToolService(repo, CONFIG, clock=world.clock)
    result = tools.call("get_report", {"investigation_id": inv.id, "claim_id": "x"})
    assert result["error"]["code"] == "NOT_FOUND"


def test_request_reset_is_admin_only_and_starts_the_worker(world):
    with pytest.raises(Forbidden):
        world.demo.request_reset(REVIEWER, "inc_demo")
    world.demo.request_reset(ADMIN, "inc_demo")
    assert world.trigger.started == [("inc_demo", "adm_1")]
    assert world.repo.list_activity("inc_demo", 1)[0].message == "Demo reset requested"


def test_only_the_demo_incident_can_be_reset():
    w = World()
    with pytest.raises(BadRequest):
        w.demo.request_reset(ADMIN, "inc_other")
    w.repo.put_incident(Incident(id="inc_demo", name="Real", is_demo=False))
    with pytest.raises(BadRequest):
        w.demo.reset("inc_demo", "adm_1")


def record_a_real_run(world):
    """A finished live run, as the runner and tools leave it."""
    repo = world.repo
    relay = world.claim("org_ngo", "FRD-0001")
    source = world.claim("org_hospital", "CHD-0001")
    starter = InvestigationService(repo, InMemoryBudgetLedger(), Queue(), CONFIG, world.clock)
    inv = starter.start(REVIEWER, relay.id).investigation
    repo.update_investigation_if(
        inv.id, S.QUEUED, {"status": S.RUNNING, "started_at": world.clock.now()}
    )
    repo.put_investigation_step(
        InvestigationStep(
            investigation_id=inv.id,
            incident_id="inc_demo",
            seq=1,
            kind=StepKind.TOOL,
            tool_name="find_reports_by_source",
            input_json=f'{{"source_id": "{source.source_id}", "subject_id": "{relay.subject_id}"}}',
            output_summary=f"1 report from Central Hospital Demo ({source.id})",
            duration_ms=90,
            created_at=world.clock.now(),
        )
    )
    world.clock.at += timedelta(seconds=19)
    result = AgentToolService(repo, CONFIG, clock=world.clock).call(
        "record_finding",
        {
            "investigation_id": inv.id,
            "attribution": "RELAY",
            "referenced_source_id": source.source_id,
            "comparison": "SUPPORTS",
            "summary": "The NGO repeats the hospital's admission report.",
            "citations": [
                {"claim_id": relay.id, "excerpt": "According to Central Hospital Demo"},
                {"claim_id": source.id, "excerpt": "admitted to ward 3 at 07:40"},
            ],
        },
    )
    assert result["ok"], result
    return world.demo.recording(ADMIN, inv.id), inv


def test_recording_names_reports_by_reference_not_id(world):
    recording, inv = record_a_real_run(world)
    assert recording["claim"] == "{claim:org_ngo/FRD-0001}"
    assert recording["referenced_source"] == "{source:Central Hospital Demo}"
    assert recording["citations"][1] == {
        "claim": "{claim:org_hospital/CHD-0001}",
        "excerpt": "admitted to ward 3 at 07:40",
    }
    step = recording["steps"][0]
    assert "{source:Central Hospital Demo}" in step["input_json"]
    assert "{subject:org_police/DPD-0001}" in step["input_json"]
    assert step["output_summary"].endswith("({claim:org_hospital/CHD-0001})")
    assert "clm_" not in str(recording) and "src_" not in str(recording)
    assert recording["model_id"] == "model-a" and recording["status"] == "NEEDS_REVIEW"


def test_recording_is_for_finished_live_runs_and_admins(world):
    with pytest.raises(NotFound):
        world.demo.recording(ADMIN, "inv_x")
    starter = InvestigationService(world.repo, InMemoryBudgetLedger(), Queue(), CONFIG, world.clock)
    queued = starter.start(REVIEWER, world.claim("org_ngo", "FRD-0001").id).investigation
    with pytest.raises(BadRequest):
        world.demo.recording(ADMIN, queued.id)
    with pytest.raises(Forbidden):
        world.demo.recording(REVIEWER, queued.id)


def test_reset_restores_recorded_runs_as_replayed_and_serves_them_cached(world):
    recording, original = record_a_real_run(world)
    replaying = World(WithRuns([recording]))
    result = replaying.demo.reset("inc_demo", "adm_1")
    assert result.replayed_runs == 1
    repo = replaying.repo
    (inv,) = repo.investigations.values()
    relay = replaying.claim("org_ngo", "FRD-0001")
    source = replaying.claim("org_hospital", "CHD-0001")
    assert inv.mode == InvestigationMode.REPLAYED and inv.id != original.id
    assert inv.claim_id == relay.id and inv.referenced_source_id == source.source_id
    assert inv.status == S.NEEDS_REVIEW and inv.outcome_reasons == ("RELAY_NOT_FIRST_HAND",)
    # Labeled with the original model and run time, never "now".
    finished = world.repo.get_investigation(original.id).finished_at
    assert inv.model_id == "model-a" and inv.finished_at == finished is not None
    for citation in inv.citations:
        assert quotes(citation.excerpt, repo.get_claim(citation.claim_id).original_text)
    (step,) = repo.list_investigation_steps(inv.id)
    assert source.id in step.output_summary and relay.subject_id in step.input_json
    item = repo.review_items[review_item_id(ReviewItemType.FINDING, inv.id)]
    assert item.priority == 3

    starter = InvestigationService(repo, InMemoryBudgetLedger(), Queue(), CONFIG, replaying.clock)
    served = starter.start(REVIEWER, relay.id)
    assert served.mode == InvestigationMode.CACHED and served.investigation.id == inv.id


def test_activity_feed_is_readable_by_incident_readers(world):
    entries = world.demo.activity(REVIEWER, "inc_demo")
    assert entries[0].message.startswith("Demo reset:")
    with pytest.raises(NotFound):
        world.demo.activity(REVIEWER, "inc_x")
    publisher = Caller(user_id="p", groups=frozenset({"publisher"}), org_id="org_x")
    with pytest.raises(Forbidden):
        world.demo.activity(publisher, "inc_demo")


def test_reference_key_matches_the_recording_format():
    assert reference_key("org_ngo", "FRD-0001") == "org_ngo/FRD-0001"
