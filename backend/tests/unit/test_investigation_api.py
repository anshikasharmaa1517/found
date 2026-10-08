from datetime import UTC, datetime, timedelta

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import InvestigationStep, Organization, Settings
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService
from found_core.services.reports import ReportService
from found_core.tools.service import AgentToolService
from tests.unit.test_api_handler import BODY, call, event, publish

REVIEWER = {"sub": "rev_1", "cognito:groups": "[reviewer]"}
ADMIN = {"sub": "adm_1", "cognito:groups": "[admin]"}
FAMILY = {"sub": "fam_1", "cognito:groups": "[family]"}
NGO_CLAIMS = {"sub": "user_n", "cognito:groups": "[publisher]", "custom:org_id": "org_n"}


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


class Queue:
    def __init__(self):
        self.sent = []

    def send(self, investigation_id):
        self.sent.append(investigation_id)


class World:
    def __init__(self, monkeypatch):
        self.clock = Clock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.settings = Settings(live_enabled=True)
        for oid, name, kind in (
            ("org_h", "Central Hospital Demo", "HOSPITAL"),
            ("org_n", "Flood Relief Demo", "NGO"),
        ):
            self.repo.add_organization(
                Organization(
                    id=oid, incident_id="inc_1", name=name, name_norm=name.lower(), org_type=kind
                )
            )
        ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        reports = ReportService(self.repo, ingest)
        self.queue = Queue()
        self.config = InvestigationConfig(model_id="model-a")
        self.service = InvestigationService(
            self.repo, InMemoryBudgetLedger(), self.queue, self.config, clock=self.clock
        )
        monkeypatch.setattr(container, "report_service", lambda: reports)
        monkeypatch.setattr(container, "investigation_service", lambda: self.service)

        _, body, _ = publish()
        self.person = body["claim"]["subject_id"]
        self.source_claim = body["claim"]["id"]
        relay = {
            **BODY,
            "subject": {"type": "PERSON", "id": self.person},
            "claim_type": "FOUND_SAFE",
            "original_text": "According to Central Hospital Demo, Maya Rawat was admitted.",
            "external_reference": "NGO-1",
        }
        _, body, _ = publish(relay, claims=NGO_CLAIMS)
        self.relay = body["claim"]["id"]

    def start(self, claim_id=None, body=None, claims=REVIEWER):
        path = f"/v1/claims/{claim_id or self.relay}/investigations"
        return call(event("POST", path, body, claims))

    def get(self, investigation_id, claims=REVIEWER):
        return call(event("GET", f"/v1/investigations/{investigation_id}", claims=claims))


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)


def test_start_queues_a_live_run(world):
    status, body, _ = world.start()
    assert status == 202
    inv_id = body["investigation_id"]
    assert body == {
        "investigation_id": inv_id,
        "mode": "LIVE",
        "status": "QUEUED",
        "ws_topic": f"investigation:{inv_id}",
    }
    assert world.queue.sent == [inv_id]


def test_finished_run_is_served_cached(world):
    _, body, _ = world.start()
    inv_id = body["investigation_id"]
    world.repo.update_investigation_if(inv_id, S.QUEUED, {"status": S.RUNNING})
    world.clock.at += timedelta(seconds=20)
    world.repo.update_investigation_if(
        inv_id, S.RUNNING, {"status": S.NEEDS_REVIEW, "finished_at": world.clock.now()}
    )
    status, body, _ = world.start()
    assert status == 200
    assert body == {
        "investigation_id": inv_id,
        "mode": "CACHED",
        "status": "NEEDS_REVIEW",
        "original_run_at": "2026-10-05T10:15:20Z",
    }


@pytest.mark.parametrize(
    ("setup", "expected_status", "code"),
    [
        (lambda w: None, 409, "IN_PROGRESS"),
        (lambda w: w.repo.__setattr__("settings", Settings()), 503, "LIVE_UNAVAILABLE"),
    ],
)
def test_start_errors_follow_the_design(world, setup, expected_status, code):
    first = None
    if code == "IN_PROGRESS":
        _, body, _ = world.start()
        first = body["investigation_id"]
    setup(world)
    status, body, _ = world.start()
    assert status == expected_status and body["error"]["code"] == code
    if first:
        assert body["error"]["details"] == {"investigation_id": first}


def test_budget_limit_is_429(world):
    world.repo.settings = Settings(live_enabled=True, run_cap=0)
    status, body, _ = world.start()
    assert status == 429 and body["error"]["code"] == "BUDGET_LIMIT"
    assert body["error"]["details"] == {"period": "2026-10", "cap": 0}


@pytest.mark.parametrize(
    ("body", "claims", "expected"),
    [
        ({"force_live": "yes"}, REVIEWER, 400),
        ({"other": 1}, REVIEWER, 400),
        ({"force_live": True}, REVIEWER, 403),
        (None, FAMILY, 403),
        (None, None, 401),
    ],
)
def test_start_checks_body_and_role(world, body, claims, expected):
    status, _, _ = world.start(body=body, claims=claims)
    assert status == expected
    assert world.queue.sent == []


def test_admin_may_force_a_live_run(world):
    status, body, _ = world.start(body={"force_live": True}, claims=ADMIN)
    assert status == 202 and body["mode"] == "LIVE"


def test_unknown_claim_is_404(world):
    status, body, _ = world.start(claim_id="clm_missing")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_detail_shows_finding_usage_timing_and_steps(world):
    _, body, _ = world.start()
    inv_id = body["investigation_id"]
    world.repo.update_investigation_if(
        inv_id, S.QUEUED, {"status": S.RUNNING, "started_at": world.clock.now()}
    )
    tools = AgentToolService(world.repo, world.config, clock=world.clock)
    source_id = world.repo.get_claim(world.source_claim).source_id
    world.clock.at += timedelta(seconds=18, milliseconds=450)
    result = tools.call(
        "record_finding",
        {
            "investigation_id": inv_id,
            "attribution": "RELAY",
            "referenced_source_id": source_id,
            "comparison": "DIFFERS",
            "summary": "The NGO says found safe; the hospital report says missing.",
            "citations": [
                {"claim_id": world.relay, "excerpt": "According to Central Hospital Demo"},
                {"claim_id": world.source_claim, "excerpt": "missing since the bridge collapse"},
            ],
        },
    )
    assert result["ok"], result
    world.repo.put_investigation_step(
        InvestigationStep(
            investigation_id=inv_id, incident_id="inc_1", seq=1, kind="TOOL",
            tool_name="record_finding", output_summary="Finding recorded: NEEDS_REVIEW",
            duration_ms=12, created_at=world.clock.now(),
        )
    )  # fmt: skip

    status, view, _ = world.get(inv_id)
    assert status == 200
    assert view["status"] == "NEEDS_REVIEW" and view["mode"] == "LIVE"
    assert (view["model_id"], view["prompt_version"]) == ("model-a", "lineage-v1")
    assert view["finding"] == {
        "attribution": "RELAY",
        "referenced_source": {"id": source_id, "name": "Central Hospital Demo"},
        "comparison": "DIFFERS",
        "summary": "The NGO says found safe; the hospital report says missing.",
        "citations": [
            {"claim_id": world.relay, "excerpt": "According to Central Hospital Demo"},
            {"claim_id": world.source_claim, "excerpt": "missing since the bridge collapse"},
        ],
    }
    assert view["outcome_reasons"] == ["RELAY_DIFFERS_FROM_SOURCE"]
    assert view["usage"]["tool_calls"] == 1
    assert view["timing"]["duration_ms"] == 18450
    assert view["steps"] == [
        {
            "seq": 1,
            "kind": "TOOL",
            "tool": "record_finding",
            "summary": "Finding recorded: NEEDS_REVIEW",
            "duration_ms": 12,
            "input_tokens": None,
            "output_tokens": None,
            "error_code": None,
        }
    ]
    assert view["review"] is None


def test_detail_of_a_queued_run_has_no_finding(world):
    _, body, _ = world.start()
    status, view, _ = world.get(body["investigation_id"])
    assert status == 200
    assert view["finding"] is None and view["steps"] == []
    assert view["timing"]["started_at"] is None and view["timing"]["duration_ms"] is None


def test_detail_is_for_reviewers_and_must_exist(world):
    _, body, _ = world.start()
    assert world.get(body["investigation_id"], claims=FAMILY)[0] == 403
    assert world.get("inv_missing")[0] == 404
