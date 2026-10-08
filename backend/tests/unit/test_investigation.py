from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.investigation import (
    CACHEABLE_STATUSES,
    TERMINAL_STATUSES,
    InvestigationConfig,
    budget_period,
    can_transition,
    fingerprint,
)
from found_core.domain.models import Investigation
from tests.unit.factories import claim

CFG = InvestigationConfig(model_id="model-a")


def relay(mentions=("src_h",)):
    return claim(2, "FOUND_SAFE", None, source_id="src_ngo").model_copy(
        update={"mentioned_source_ids": tuple(mentions)}
    )


def test_fingerprint_is_stable_and_ignores_mention_order():
    a = fingerprint(relay(("src_a", "src_b")), ["src_a", "src_b"], {"src_a": "c1"}, CFG)
    b = fingerprint(relay(("src_b", "src_a")), ["src_b", "src_a", "src_a"], {"src_a": "c1"}, CFG)
    assert a == b
    assert a.startswith("fp_") and len(a) == 35


@pytest.mark.parametrize(
    "change",
    [
        {"latest": {"src_h": "clm_new"}},
        {"cfg": InvestigationConfig(model_id="model-b")},
        {"cfg": InvestigationConfig(model_id="model-a", prompt_version="lineage-v2")},
        {"cfg": InvestigationConfig(model_id="model-a", agent_version="0.2.0")},
        {"claim": relay().model_copy(update={"payload_hash": "sha256:other"})},
        {"mentions": []},
    ],
)
def test_fingerprint_changes_with_evidence_or_versions(change):
    base = fingerprint(relay(), ["src_h"], {"src_h": "clm_1"}, CFG)
    changed = fingerprint(
        change.get("claim", relay()),
        change.get("mentions", ["src_h"]),
        change.get("latest", {"src_h": "clm_1"}),
        change.get("cfg", CFG),
    )
    assert changed != base


def test_fingerprint_treats_a_source_without_claims_as_empty():
    assert fingerprint(relay(), ["src_h"], {}, CFG) == fingerprint(
        relay(), ["src_h"], {"src_h": None}, CFG
    )


def test_status_machine_follows_the_design():
    assert can_transition(S.QUEUED, S.RUNNING)
    assert can_transition(S.QUEUED, S.FAILED)
    assert not can_transition(S.QUEUED, S.COMPLETED)
    for target in (S.COMPLETED, S.NEEDS_REVIEW, S.FAILED):
        assert can_transition(S.RUNNING, target)
    assert not can_transition(S.RUNNING, S.QUEUED)
    assert TERMINAL_STATUSES == {S.COMPLETED, S.NEEDS_REVIEW, S.FAILED}
    for terminal in TERMINAL_STATUSES:
        assert not any(can_transition(terminal, t) for t in S)
    assert CACHEABLE_STATUSES == {S.COMPLETED, S.NEEDS_REVIEW}


def test_budget_period_is_the_utc_month():
    nepal = timezone(timedelta(hours=5, minutes=45))
    assert budget_period(datetime(2026, 11, 1, 3, 0, tzinfo=nepal)) == "2026-10"
    assert budget_period(datetime(2026, 10, 31, 23, 0, tzinfo=UTC)) == "2026-10"
    with pytest.raises(ValueError):
        budget_period(datetime(2026, 10, 1))


def test_limits_match_design_defaults():
    assert CFG.limits() == {
        "max_tool_calls": 8,
        "max_model_turns": 6,
        "wall_clock_seconds": 120,
        "max_output_tokens": 512,
    }
    assert (CFG.run_cap, CFG.model_call_cap, CFG.lock_ttl) == (200, 1200, timedelta(minutes=10))


def test_cached_is_never_a_stored_mode():
    with pytest.raises(ValidationError):
        Investigation(
            id="inv_1",
            incident_id="inc_1",
            claim_id="clm_1",
            fingerprint="fp_1",
            mode="CACHED",
            status="QUEUED",
            model_id="model-a",
            prompt_version="lineage-v1",
            agent_version="0.1.0",
            created_by="rev_1",
            queued_at=datetime(2026, 10, 5, tzinfo=UTC),
        )
