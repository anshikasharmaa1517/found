"""Run the eval set against a Bedrock model.

    python -m evals.run --model-id <id> [--baseline evals/baseline.json] [--save-baseline]

Needs AWS credentials with access to the model in the region. Every case is a real
model run: it costs tokens. Exit code 1 means the gate failed, 0 means the change may
ship. The report is written as JSON for the record.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from found_core.domain.investigation import InvestigationConfig

from evals.cases import CASES
from evals.harness import Prices, gate, run_case, summarize
from found_agent.app import bedrock_model
from found_agent.config import AGENT_VERSION, AgentConfig
from found_agent.prompts import PROMPT_VERSION

HERE = Path(__file__).parent


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--guardrail-id")
    parser.add_argument("--guardrail-version")
    parser.add_argument("--case", action="append", help="Run only these case ids.")
    parser.add_argument("--price-in", type=float, default=0.0, help="USD per 1,000 input tokens")
    parser.add_argument("--price-out", type=float, default=0.0, help="USD per 1,000 output tokens")
    parser.add_argument("--baseline", type=Path, default=HERE / "baseline.json")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--out", type=Path, default=HERE / "last_report.json")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    cases = [c for c in CASES if not args.case or c.id in args.case]
    if not cases:
        print("No cases match.", file=sys.stderr)
        return 2
    agent_config = AgentConfig(
        model_id=args.model_id,
        gateway_url="",
        region=args.region,
        guardrail_id=args.guardrail_id,
        guardrail_version=args.guardrail_version,
    )
    config = InvestigationConfig(
        model_id=args.model_id, prompt_version=PROMPT_VERSION, agent_version=AGENT_VERSION
    )
    results = []
    for case in cases:
        # A fresh model client per case keeps runs independent.
        result = await run_case(
            case,
            lambda _world: bedrock_model(agent_config, config.max_output_tokens),
            config,
            model_id=args.model_id,
        )
        mark = "ok " if result.attribution_ok and result.comparison_ok else "BAD"
        print(
            f"{mark} {case.id}: {result.attribution}/{result.comparison} "
            f"source={result.referenced_source} status={result.status} "
            f"tools={result.tool_calls} {result.latency_s}s"
        )
        results.append(result)

    report = summarize(
        results, model_id=args.model_id, prices=Prices(args.price_in, args.price_out)
    )
    args.out.write_text(json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8")
    baseline = None
    if args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    problems = gate(report, baseline)
    print(
        f"\nattribution {report.attribution_accuracy:.0%}, comparison "
        f"{report.comparison_accuracy:.0%}, source {report.source_accuracy:.0%}, findings "
        f"{report.finding_rate:.0%}, citations valid {report.citation_validity}, avg tools "
        f"{report.avg_tool_calls}, p95 {report.p95_latency_s}s, cost ${report.cost_usd}"
    )
    for problem in problems:
        print(f"GATE: {problem}", file=sys.stderr)
    if args.save_baseline and not problems:
        summary = {k: v for k, v in report.to_json().items() if k != "results"}
        args.baseline.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
