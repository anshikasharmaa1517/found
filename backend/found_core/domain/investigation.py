"""Investigation control rules (design Section 9.8). Pure: no I/O.

The fingerprint names the evidence a run would read. Equal fingerprints mean a stored
result can be served again without a model call; any new claim at the top of a
mentioned source's feed, or a new prompt, agent or model, changes it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from found_core.domain.enums import InvestigationStatus
from found_core.domain.hashing import canonical_json, sha256_hex
from found_core.domain.models import Claim

_S = InvestigationStatus

ALLOWED_TRANSITIONS: dict[InvestigationStatus, frozenset[InvestigationStatus]] = {
    _S.QUEUED: frozenset({_S.RUNNING, _S.FAILED}),
    _S.RUNNING: frozenset({_S.COMPLETED, _S.NEEDS_REVIEW, _S.FAILED}),
    _S.COMPLETED: frozenset(),
    _S.NEEDS_REVIEW: frozenset(),
    _S.FAILED: frozenset(),
}

# Only these may be served from the cache. A failure is never reused.
CACHEABLE_STATUSES: frozenset[InvestigationStatus] = frozenset({_S.COMPLETED, _S.NEEDS_REVIEW})
TERMINAL_STATUSES: frozenset[InvestigationStatus] = frozenset(
    s for s, nxt in ALLOWED_TRANSITIONS.items() if not nxt
)


@dataclass(frozen=True)
class InvestigationConfig:
    """Versions that define a run, and the limits from design Section 9.8."""

    model_id: str
    prompt_version: str = "lineage-v1"
    agent_version: str = "0.1.0"
    max_tool_calls: int = 8
    max_model_turns: int = 6
    wall_clock_seconds: int = 120
    max_output_tokens: int = 512
    run_cap: int = 200
    model_call_cap: int = 1200
    lock_ttl: timedelta = timedelta(minutes=10)

    def limits(self) -> dict[str, int]:
        """What the runner hands the agent. Code enforces each one again on its side."""
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_model_turns": self.max_model_turns,
            "wall_clock_seconds": self.wall_clock_seconds,
            "max_output_tokens": self.max_output_tokens,
        }


def fingerprint(
    claim: Claim,
    mentioned_source_ids: Sequence[str],
    latest_claim_ids: Mapping[str, str | None],
    cfg: InvestigationConfig,
) -> str:
    parts = {
        "prompt": cfg.prompt_version,
        "agent": cfg.agent_version,
        "model": cfg.model_id,
        "claim": claim.payload_hash,
        "evidence": sorted(
            [sid, latest_claim_ids.get(sid) or ""] for sid in set(mentioned_source_ids)
        ),
    }
    return "fp_" + sha256_hex(canonical_json(parts))[:32]


def can_transition(current: InvestigationStatus, target: InvestigationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def budget_period(now: datetime) -> str:
    """Monthly budget key, `yyyy-mm` in UTC."""
    if now.tzinfo is None:
        raise ValueError("budget period needs an aware datetime")
    return now.astimezone(UTC).strftime("%Y-%m")
