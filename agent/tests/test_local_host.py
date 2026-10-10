from datetime import UTC, datetime

from found_core.adapters.local_agent import LocalAgentInvoker, local_tools
from found_core.adapters.memory import InMemoryBudgetLedger
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.enums import StepKind
from found_core.domain.investigation import InvestigationConfig
from found_core.ports.agent import AgentTimeout, AgentUnavailable
from found_core.services.runner import InvestigationRunner
from found_core.tools.service import AgentToolService

from evals.cases import CASES
from evals.world import World
from tests.stubs import ScriptedModel

CONFIG = InvestigationConfig(model_id="stub")
CASE = next(c for c in CASES if c.id == "relay-supports-admission")


class Clock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def queued_world():
    """An incident with a QUEUED investigation of the relay, as the API leaves it."""
    world = World.build(CASE, CONFIG)
    inv = world.result()
    world.repo.update_investigation_if(inv.id, S.RUNNING, {"status": S.QUEUED})
    return world


def correct_model(world):
    target = world.target()
    source = world.sources["Central Hospital Demo"]
    hospital = next(c for c in world.claims.values() if c.source_id == source.id)
    finding = {
        "attribution": "RELAY",
        "referenced_source_id": source.id,
        "comparison": "SUPPORTS",
        "summary": "Repeats the hospital report.",
        "citations": [
            {"claim_id": target.id, "excerpt": target.original_text[:40]},
            {"claim_id": hospital.id, "excerpt": hospital.original_text[:40]},
        ],
    }
    # Tool names without the Gateway prefix, as the local tools are named.
    return ScriptedModel(
        [
            [("tool", "get_report", {"claim_id": target.id})],
            [("tool", "record_finding", finding)],
        ],
        prefix="",
    )


def test_the_runner_drives_the_agent_in_process_end_to_end():
    world = queued_world()
    tools = AgentToolService(world.repo, CONFIG, clock=Clock())
    invoker = LocalAgentInvoker(
        tools, lambda: correct_model(world), model_id="stub", read_timeout=30
    )
    runner = InvestigationRunner(world.repo, InMemoryBudgetLedger(), invoker, CONFIG, Clock())
    result = runner.run(world.result().id)

    inv = world.result()
    assert result.status == S.NEEDS_REVIEW and inv.outcome_reasons == ("RELAY_NOT_FIRST_HAND",)
    assert inv.tool_calls == 2 and inv.model_calls == 2
    kinds = [s.kind for s in world.repo.list_investigation_steps(inv.id)]
    assert kinds == [StepKind.MODEL, StepKind.TOOL, StepKind.MODEL, StepKind.TOOL]
    assert world.target().id not in world.repo.run_locks


def test_local_tools_answer_with_the_services_json():
    world = queued_world()
    names = [t.tool_name for t in local_tools(AgentToolService(world.repo, CONFIG))]
    assert names == [
        "get_report",
        "list_mentioned_sources",
        "find_reports_by_source",
        "get_person_timeline",
        "search_people",
        "record_finding",
    ]


def test_a_broken_model_client_surfaces_as_unavailable():
    world = queued_world()

    def broken():
        raise RuntimeError("no credentials")

    invoker = LocalAgentInvoker(
        AgentToolService(world.repo, CONFIG), broken, model_id="stub", read_timeout=30
    )
    target = world.target()
    payload = {
        "investigation_id": world.result().id,
        "claim_id": target.id,
        "incident_id": target.incident_id,
    }
    try:
        list(invoker.invoke("s", payload))
        raise AssertionError("expected the run to be reported unavailable")
    except AgentUnavailable as err:
        # The runner records this as FAILED with AGENT_UNAVAILABLE.
        assert str(err) == "RuntimeError"


def test_silence_past_the_read_timeout_is_a_timeout():
    import threading

    world = queued_world()
    gate = threading.Event()

    class Slow(ScriptedModel):
        async def stream(self, *args, **kwargs):
            gate.wait(5)
            async for event in super().stream(*args, **kwargs):
                yield event

    invoker = LocalAgentInvoker(
        AgentToolService(world.repo, CONFIG),
        lambda: Slow([]),
        model_id="stub",
        read_timeout=0.2,
    )
    payload = {
        "investigation_id": world.result().id,
        "claim_id": world.target().id,
        "incident_id": world.target().incident_id,
    }
    events = invoker.invoke("s", payload)
    assert next(events)["type"] == "start"
    try:
        next(events)
        raise AssertionError("expected a timeout")
    except AgentTimeout:
        pass
    finally:
        gate.set()
