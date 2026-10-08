import asyncio

import pytest
from found_core.domain.enums import Attribution, Comparison
from found_core.domain.investigation import InvestigationConfig

from evals import run as eval_run
from evals.cases import CASES, CATEGORIES, Case
from evals.harness import Prices, gate, run_case, summarize
from evals.world import World
from tests.stubs import ScriptedModel

CONFIG = InvestigationConfig(model_id="stub")


def oracle(world: World) -> ScriptedModel:
    """Plays the procedure a careful reviewer would, with the case's labels."""
    case = world.case
    target = world.target()
    turns = [
        [("tool", "get_report", {"claim_id": target.id})],
        [("tool", "list_mentioned_sources", {"claim_id": target.id})],
    ]
    citations = [{"claim_id": target.id, "excerpt": target.original_text[:40]}]
    source_id = None
    if case.referenced_source:
        source = world.sources[case.referenced_source]
        source_id = source.id
        own = [c for c in world.claims.values() if c.source_id == source.id]
        turns.append(
            [
                (
                    "tool",
                    "find_reports_by_source",
                    {"source_id": source.id, "subject_id": target.subject_id},
                )
            ]
        )
        if own:
            citations.append({"claim_id": own[0].id, "excerpt": own[0].original_text[:40]})
    finding = {
        "attribution": case.attribution,
        "comparison": case.comparison,
        "summary": f"Labels for {case.id}.",
        "citations": citations,
    }
    if source_id:
        finding["referenced_source_id"] = source_id
    turns.append([("tool", "record_finding", finding)])
    return ScriptedModel(turns)


def always_direct(world: World) -> ScriptedModel:
    target = world.target()
    finding = {
        "attribution": "DIRECT",
        "comparison": "NOT_APPLICABLE",
        "summary": "Treated as first-hand.",
        "citations": [{"claim_id": target.id, "excerpt": target.original_text[:40]}],
    }
    return ScriptedModel([[("tool", "record_finding", finding)]])


def invents_quotes(world: World) -> ScriptedModel:
    target = world.target()
    finding = {
        "attribution": "DIRECT",
        "comparison": "NOT_APPLICABLE",
        "summary": "Made up.",
        "citations": [{"claim_id": target.id, "excerpt": "words that are not in the report"}],
    }
    return ScriptedModel([[("tool", "record_finding", finding)]] * 3)


def run_all(model_for, cases=CASES):
    async def go():
        return [await run_case(c, model_for, CONFIG, model_id="stub") for c in cases]

    return asyncio.run(go())


def test_cases_cover_the_design_set():
    assert len(CASES) == 20
    assert len({c.id for c in CASES}) == 20
    assert {c.category for c in CASES} == set(CATEGORIES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_case_is_well_formed(case: Case):
    keys = [r.key for r in case.reports]
    assert len(keys) == len(set(keys)) and case.target in keys
    Attribution(case.attribution)
    Comparison(case.comparison)
    target = next(r for r in case.reports if r.key == case.target)
    if case.referenced_source:
        # The source a reviewer would name is spelled correctly in the text.
        assert case.referenced_source in target.text
    if case.category == "misspelled_source":
        assert case.referenced_source is None
    if case.attribution == "DIRECT":
        assert case.comparison == "NOT_APPLICABLE" and case.referenced_source is None


def test_a_correct_agent_scores_full_marks_and_passes_the_gate():
    results = run_all(oracle)
    report = summarize(results, model_id="stub")
    bad = [r.case_id for r in results if not (r.attribution_ok and r.comparison_ok)]
    assert bad == []
    assert report.finding_rate == 1.0 and report.source_accuracy == 1.0
    assert report.citation_validity == 1.0
    assert all(r.rejected_findings == 0 for r in results)
    assert gate(report, {"attribution_accuracy": 1.0}) == []


def test_outcomes_come_from_code_not_the_case():
    results = {r.case_id: r for r in run_all(oracle)}
    assert results["direct-hospital-admission"].status == "COMPLETED"
    assert results["relay-supports-admission"].outcome_reasons == ("RELAY_NOT_FIRST_HAND",)
    assert results["relay-differs-status"].outcome_reasons == ("RELAY_DIFFERS_FROM_SOURCE",)
    assert results["relay-source-silent"].outcome_reasons == ("SOURCE_NOT_FOUND",)
    assert results["misspelled-hospital"].outcome_reasons == ("SOURCE_NOT_FOUND",)
    assert results["unclear-hearsay"].outcome_reasons == ("ATTRIBUTION_UNCLEAR",)
    # No relay is ever completed on its own, even when it agrees with its source.
    relays = [r for r in results.values() if r.attribution == "RELAY"]
    assert relays and all(r.status == "NEEDS_REVIEW" for r in relays)


def test_misspelled_source_is_not_on_the_menu():
    case = next(c for c in CASES if c.id == "misspelled-hospital")
    world = World.build(case, CONFIG)
    assert world.target().mentioned_source_ids == ()


def test_a_wrong_agent_is_scored_down_and_fails_against_the_baseline():
    report = summarize(run_all(always_direct), model_id="stub")
    expected = sum(c.attribution == "DIRECT" for c in CASES) / len(CASES)
    assert report.attribution_accuracy == expected
    assert report.citation_validity == 1.0
    assert gate(report, {"attribution_accuracy": 1.0}) == [
        f"attribution accuracy dropped from 100% to {expected:.0%}"
    ]
    assert report.by_category["direct"] == 1.0 and report.by_category["clean_relay"] == 0.0


def test_invented_quotes_are_refused_so_nothing_is_recorded():
    cases = CASES[:3]
    results = run_all(invents_quotes, cases)
    assert all(not r.finding_recorded and r.rejected_findings >= 1 for r in results)
    # No runner here to fail the run; production marks it FAILED with NO_FINDING.
    assert all(r.status == "RUNNING" for r in results)
    report = summarize(results, model_id="stub")
    assert report.citation_validity is None
    assert "no case recorded a finding" in gate(report)


def test_cost_and_latency_summary():
    results = run_all(oracle, CASES[:2])
    report = summarize(results, model_id="stub", prices=Prices(0.5, 2.0))
    expected = report.input_tokens / 1000 * 0.5 + report.output_tokens / 1000 * 2.0
    assert report.cost_usd == round(expected, 4) and report.cost_usd > 0
    assert report.p95_latency_s == max(r.latency_s for r in results) and report.cases == 2
    assert report.avg_tool_calls > 0


def test_cli_needs_a_known_case():
    assert eval_run.main(["--model-id", "stub", "--case", "no-such-case"]) == 2
