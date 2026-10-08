"""Run eval cases through the agent loop and score the stored results.

Scores come from what was stored, never from what the model said it did: a finding
counts only if `record_finding` accepted it, and its citations are checked again here
against the stored report text.
"""

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from found_core.domain.findings import quotes
from found_core.domain.investigation import InvestigationConfig
from strands.models.model import Model

from evals.cases import Case
from evals.world import World
from found_agent.config import AGENT_VERSION
from found_agent.prompts import PROMPT_VERSION
from found_agent.run import RunRequest, run_investigation


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    finding_recorded: bool
    attribution: str | None
    comparison: str | None
    referenced_source: str | None
    status: str
    outcome_reasons: tuple[str, ...]
    attribution_ok: bool
    comparison_ok: bool
    source_ok: bool
    citations: int
    citations_valid: bool | None
    rejected_findings: int
    tool_calls: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    latency_s: float
    stop_reason: str | None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Prices:
    """US dollars per 1,000 tokens. Set from the model's price list; nothing is assumed."""

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0


@dataclass(frozen=True)
class Report:
    model_id: str
    prompt_version: str
    agent_version: str
    cases: int
    finding_rate: float
    attribution_accuracy: float
    comparison_accuracy: float
    source_accuracy: float
    citation_validity: float | None
    avg_tool_calls: float
    p95_latency_s: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    by_category: dict[str, float] = field(default_factory=dict)
    results: tuple[CaseResult, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _citations_valid(world: World) -> tuple[int, bool | None]:
    inv = world.result()
    if not inv.citations:
        return 0, None
    for citation in inv.citations:
        claim = world.repo.get_claim(citation.claim_id)
        if claim is None or claim.incident_id != inv.incident_id:
            return len(inv.citations), False
        if not quotes(citation.excerpt, claim.original_text):
            return len(inv.citations), False
    return len(inv.citations), True


ModelFactory = Callable[[World], Model]


async def run_case(
    case: Case, model_for: ModelFactory, config: InvestigationConfig, *, model_id: str
) -> CaseResult:
    """`model_for` gets the seeded world; a live model ignores it, a scripted one reads ids."""
    world = World.build(case, config)
    model = model_for(world)
    target = world.target()
    request = RunRequest(
        investigation_id=world.result().id,
        claim_id=target.id,
        incident_id=target.incident_id,
        limits=config.limits(),
    )
    started = time.monotonic()
    done: dict[str, Any] = {}
    async for event in run_investigation(
        request, model, world.tools(), model_id=model_id, agent_version=AGENT_VERSION
    ):
        if event.get("type") == "done":
            done = event
    latency = time.monotonic() - started

    inv = world.result()
    names = {s.id: s.name for s in world.sources.values()}
    source_name = names.get(inv.referenced_source_id) if inv.referenced_source_id else None
    recorded = inv.attribution is not None
    citations, valid = _citations_valid(world)
    usage = done.get("usage") or {}
    rejected = sum(
        1
        for name, _, body in world.tool_log
        if name == "record_finding" and (body.get("error") or {}).get("code") == "FINDING_REJECTED"
    )
    return CaseResult(
        case_id=case.id,
        category=case.category,
        finding_recorded=recorded,
        attribution=inv.attribution.value if inv.attribution else None,
        comparison=inv.comparison.value if inv.comparison else None,
        referenced_source=source_name,
        status=inv.status.value,
        outcome_reasons=inv.outcome_reasons,
        attribution_ok=recorded and inv.attribution == case.attribution,
        comparison_ok=recorded and inv.comparison == case.comparison,
        source_ok=recorded and source_name == case.referenced_source,
        citations=citations,
        citations_valid=valid,
        rejected_findings=rejected,
        tool_calls=inv.tool_calls,
        model_calls=int(done.get("model_calls") or 0),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        latency_s=round(latency, 3),
        stop_reason=done.get("stop_reason"),
        failure_reason=inv.failure_reason,
    )


def _share(flags: Sequence[bool]) -> float:
    return round(sum(flags) / len(flags), 4) if flags else 0.0


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


NO_PRICES = Prices()


def summarize(
    results: Sequence[CaseResult], *, model_id: str, prices: Prices = NO_PRICES
) -> Report:
    recorded = [r for r in results if r.finding_recorded]
    checked = [r.citations_valid for r in recorded if r.citations_valid is not None]
    input_tokens = sum(r.input_tokens for r in results)
    output_tokens = sum(r.output_tokens for r in results)
    categories = sorted({r.category for r in results})
    return Report(
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        agent_version=AGENT_VERSION,
        cases=len(results),
        finding_rate=_share([r.finding_recorded for r in results]),
        attribution_accuracy=_share([r.attribution_ok for r in results]),
        comparison_accuracy=_share([r.comparison_ok for r in results]),
        source_accuracy=_share([r.source_ok for r in results]),
        citation_validity=_share(checked) if checked else None,
        avg_tool_calls=round(sum(r.tool_calls for r in results) / len(results), 2)
        if results
        else 0.0,
        p95_latency_s=_p95([r.latency_s for r in results]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(
            input_tokens / 1000 * prices.input_per_1k + output_tokens / 1000 * prices.output_per_1k,
            4,
        ),
        by_category={
            c: _share([r.attribution_ok for r in results if r.category == c]) for c in categories
        },
        results=tuple(results),
    )


def gate(report: Report, baseline: dict[str, Any] | None = None) -> list[str]:
    """Reasons a model or prompt change may not ship (design Section 9.9). Empty means it may."""
    problems: list[str] = []
    if report.citation_validity is not None and report.citation_validity < 1.0:
        problems.append(f"citation validity is {report.citation_validity:.0%}, it must be 100%")
    if report.finding_rate == 0.0:
        problems.append("no case recorded a finding")
    if baseline is not None:
        before = float(baseline.get("attribution_accuracy", 0.0))
        if report.attribution_accuracy < before:
            problems.append(
                f"attribution accuracy dropped from {before:.0%} to "
                f"{report.attribution_accuracy:.0%}"
            )
    return problems
