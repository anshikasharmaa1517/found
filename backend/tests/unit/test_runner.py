from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.enums import StepKind
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import Settings
from found_core.ports.agent import AgentTimeout, AgentUnavailable
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService
from found_core.services.runner import InvestigationRunner, session_id
from found_core.tools.service import AgentToolService

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class Ticker:
    """Monotonic clock that moves on each read, to test the wall clock."""

    def __init__(self, step=0.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


class Queue:
    def send(self, investigation_id):
        pass


class ScriptedInvoker:
    def __init__(self, events, raise_after=None):
        self.events = events
        self.raise_after = raise_after
        self.calls = []

    def invoke(self, session, payload):
        self.calls.append((session, payload))
        for event in self.events:
            yield event() if callable(event) else event
        if self.raise_after is not None:
            raise self.raise_after


class World:
    def __init__(self, model_call_cap=1200, ticker=None):
        self.clock = FixedClock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.settings = Settings(live_enabled=True)
        self.ledger = InMemoryBudgetLedger()
        self.config = InvestigationConfig(model_id="model-a", model_call_cap=model_call_cap)
        ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.source = self.publish(ingest, HOSPITAL, "Maya Rawat admitted to ward 3, stable.")
        self.relay = self.publish(
            ingest, NGO, "According to Central Hospital Demo, Maya R. was admitted.", self.source
        )
        starter = InvestigationService(self.repo, self.ledger, Queue(), self.config, self.clock)
        self.inv = starter.start(REVIEWER, self.relay.id).investigation
        self.tools = AgentToolService(self.repo, self.config, clock=self.clock)
        self.ticker = ticker or Ticker()

    @staticmethod
    def publish(ingest, org, text, about=None):
        subject = (
            {"type": "PERSON", "id": about.subject_id}
            if about
            else {"type": "PERSON", "new": {"name": "Maya Rawat"}}
        )
        return ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": "FOUND_SAFE",
                    "original_text": text,
                    "external_reference": f"REF-{org['org_id']}",
                    "reported_at": "2026-10-05T08:00:00Z",
                }
            )
        ).claim

    def runner(self, invoker):
        return InvestigationRunner(
            self.repo, self.ledger, invoker, self.config, self.clock, monotonic=self.ticker
        )

    def start_event(self, **overrides):
        return {
            "type": "start",
            "model_id": "model-a",
            "prompt_version": "lineage-v1",
            "agent_version": "0.1.0",
            **overrides,
        }

    def record_finding(self):
        """What the agent's record_finding call does on the tools side."""
        return self.tools.call(
            "record_finding",
            {
                "investigation_id": self.inv.id,
                "attribution": "RELAY",
                "referenced_source_id": self.source.source_id,
                "comparison": "SUPPORTS",
                "summary": "Repeats the hospital report.",
                "citations": [
                    {"claim_id": self.relay.id, "excerpt": "According to Central Hospital Demo"},
                    {"claim_id": self.source.id, "excerpt": "admitted to ward 3, stable"},
                ],
            },
        )

    def stored(self):
        return self.repo.get_investigation(self.inv.id)


def model_step(n=1):
    return {
        "type": "step",
        "step": {
            "kind": "MODEL",
            "duration_ms": 40,
            "input_tokens": 100 * n,
            "output_tokens": 10,
            "output_summary": "Requested record_finding",
        },
    }


def done(**overrides):
    return {
        "type": "done",
        "finding_recorded": True,
        "stop_reason": "FINDING_RECORDED",
        "error_code": None,
        "model_calls": 2,
        "tool_calls": 1,
        "usage": {"input_tokens": 300, "output_tokens": 20, "usage_source": "provider"},
        **overrides,
    }


@pytest.fixture
def world():
    return World()


def test_successful_run_stores_steps_usage_and_keeps_the_finding(world):
    def tool_step():
        result = world.record_finding()
        assert result["ok"]
        return {
            "type": "step",
            "step": {
                "kind": "TOOL",
                "tool": "record_finding",
                "input": {"comparison": "SUPPORTS"},
                "output_summary": "Finding recorded: NEEDS_REVIEW",
                "duration_ms": 12,
            },
        }

    invoker = ScriptedInvoker(
        [world.start_event(), model_step(1), tool_step, model_step(2), done()]
    )
    result = world.runner(invoker).run(world.inv.id)
    assert result.status == S.NEEDS_REVIEW and result.steps == 3

    session, payload = invoker.calls[0]
    assert session == session_id(world.inv.id) and len(session) >= 33
    assert payload == {
        "investigation_id": world.inv.id,
        "claim_id": world.relay.id,
        "incident_id": "inc_1",
        "limits": world.config.limits(),
    }
    inv = world.stored()
    assert inv.started_at == world.clock.now()
    assert (inv.model_calls, inv.input_tokens, inv.output_tokens) == (2, 300, 20)
    assert inv.usage_source == "provider" and inv.tool_calls == 1
    steps = world.repo.list_investigation_steps(world.inv.id)
    assert [(s.seq, s.kind, s.tool_name) for s in steps] == [
        (1, StepKind.MODEL, None),
        (2, StepKind.TOOL, "record_finding"),
        (3, StepKind.MODEL, None),
    ]
    assert steps[1].input_json == '{"comparison": "SUPPORTS"}'
    assert steps[0].input_tokens == 100 and steps[0].incident_id == "inc_1"
    usage = world.ledger.usage("2026-10")
    assert (usage.model_calls, usage.input_tokens, usage.output_tokens) == (2, 300, 20)
    assert world.relay.id not in world.repo.run_locks


@pytest.mark.parametrize(
    "ending, reason",
    [
        (done(finding_recorded=False, stop_reason="END_TURN"), "NO_FINDING"),
        (done(finding_recorded=False, stop_reason="TURN_LIMIT"), "TURN_LIMIT"),
        (done(finding_recorded=False, stop_reason="WALL_CLOCK"), "TIMEOUT"),
        (
            done(finding_recorded=False, stop_reason="ERROR", error_code="AGENT_ERROR"),
            "AGENT_ERROR",
        ),
        (None, "NO_FINDING"),
    ],
)
def test_run_without_a_finding_fails_with_a_reason(world, ending, reason):
    events = [world.start_event(), model_step()] + ([ending] if ending else [])
    result = world.runner(ScriptedInvoker(events)).run(world.inv.id)
    inv = world.stored()
    assert result.status == S.FAILED and inv.failure_reason == reason
    assert inv.finished_at == world.clock.now()
    assert world.repo.find_cached_investigation(inv.fingerprint) is None
    assert world.relay.id not in world.repo.run_locks


def test_version_mismatch_stops_before_any_step(world):
    invoker = ScriptedInvoker([world.start_event(model_id="model-b"), model_step(), done()])
    world.runner(invoker).run(world.inv.id)
    inv = world.stored()
    assert inv.status == S.FAILED and inv.failure_reason == "VERSION_MISMATCH"
    steps = world.repo.list_investigation_steps(world.inv.id)
    assert [s.kind for s in steps] == [StepKind.GUARD]


def test_wall_clock_stops_reading_and_a_late_finding_is_refused():
    world = World(ticker=Ticker(step=50.0))
    invoker = ScriptedInvoker([world.start_event(), model_step(), model_step(2), done()])
    world.runner(invoker).run(world.inv.id)
    inv = world.stored()
    assert inv.status == S.FAILED and inv.failure_reason == "TIMEOUT"
    assert world.repo.list_investigation_steps(world.inv.id)[-1].output_summary == (
        "Stopped: the wall clock limit"
    )
    # The agent may still be running; its finding can no longer be written.
    assert world.record_finding()["error"]["code"] == "NOT_RUNNING"


def test_silent_agent_times_out(world):
    world.runner(ScriptedInvoker([world.start_event()], AgentTimeout())).run(world.inv.id)
    assert world.stored().failure_reason == "TIMEOUT"


def test_unreachable_agent_fails_with_an_error_step(world):
    world.runner(ScriptedInvoker([], AgentUnavailable("AccessDeniedException"))).run(world.inv.id)
    inv = world.stored()
    assert inv.status == S.FAILED and inv.failure_reason == "AGENT_UNAVAILABLE"
    step = world.repo.list_investigation_steps(world.inv.id)[0]
    assert (step.kind, step.error_code) == (StepKind.ERROR, "AGENT_UNAVAILABLE")


def test_monthly_model_call_cap_stops_the_run():
    world = World(model_call_cap=1)
    invoker = ScriptedInvoker([world.start_event(), model_step(), model_step(2), done()])
    world.runner(invoker).run(world.inv.id)
    inv = world.stored()
    assert inv.failure_reason == "MODEL_CALL_CAP"
    assert world.ledger.usage("2026-10").model_calls == 1


def test_redelivered_running_run_is_failed_not_repeated(world):
    world.repo.update_investigation_if(world.inv.id, S.QUEUED, {"status": S.RUNNING})
    invoker = ScriptedInvoker([world.start_event(), done()])
    result = world.runner(invoker).run(world.inv.id)
    assert result.skipped_reason == "REDELIVERED"
    assert world.stored().failure_reason == "RUNNER_INTERRUPTED"
    assert invoker.calls == []
    assert world.relay.id not in world.repo.run_locks


def test_finished_or_missing_runs_are_skipped(world):
    world.repo.update_investigation_if(world.inv.id, S.QUEUED, {"status": S.FAILED})
    invoker = ScriptedInvoker([])
    assert world.runner(invoker).run(world.inv.id).skipped_reason == "ALREADY_DONE"
    assert world.runner(invoker).run("inv_gone").skipped_reason == "NOT_FOUND"
    assert invoker.calls == []


def test_fail_queued_never_leaves_a_run_queued(world):
    runner = world.runner(ScriptedInvoker([]))
    assert runner.fail_queued(world.inv.id, "RUNNER_ERROR")
    assert world.stored().failure_reason == "RUNNER_ERROR"
    assert not runner.fail_queued(world.inv.id, "RUNNER_ERROR")
    assert world.relay.id not in world.repo.run_locks


def test_unknown_step_kinds_and_oversized_fields_are_stored_safely(world):
    odd = {
        "type": "step",
        "step": {
            "kind": "THINKING",
            "output_summary": "x" * 5000,
            "duration_ms": "fast",
            "input": {"note": "y" * 5000},
        },
    }
    world.runner(ScriptedInvoker([world.start_event(), odd, done()])).run(world.inv.id)
    step = world.repo.list_investigation_steps(world.inv.id)[0]
    assert step.kind == StepKind.ERROR and step.duration_ms is None
    assert len(step.output_summary) == 2048 and len(step.input_json) == 2048
