from datetime import UTC, datetime

import pytest

from found_core.domain.commands import PublishCommand
from found_core.domain.errors import ValidationFailed
from found_core.domain.ids import source_id, ulid


def _data(**overrides):
    base = {
        "incident_id": "inc_1",
        "org_id": "org_h",
        "org_name": "Central Hospital Demo",
        "org_type": "HOSPITAL",
        "actor": "user_1",
        "subject": {"type": "PERSON", "new": {"name": "Maya Rawat", "age": 24}},
        "claim_type": "FOUND_SAFE",
        "original_text": "Maya Rawat, 24, admitted, stable.",
        "external_reference": "CH-0412",
        "reported_at": "2026-10-03T07:40:00+05:30",
    }
    base.update(overrides)
    return base


def test_reported_at_is_normalized_to_utc():
    cmd = PublishCommand.parse(_data())
    assert cmd.reported_at_utc() == datetime(2026, 10, 3, 2, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "overrides",
    [
        {"claim_type": "BRIDGE_OPEN"},
        {"external_reference": "has spaces"},
        {"reported_at": "2026-10-03T07:40:00"},
        {"reported_at": "yesterday"},
        {"subject": {"type": "PERSON"}},
        {"subject": {"type": "SHELTER", "new": {"name": "Camp", "age": 3}}},
        {"original_text": ""},
        {"unexpected": "field"},
    ],
)
def test_invalid_reports_raise_validation_failed(overrides):
    with pytest.raises(ValidationFailed) as exc:
        PublishCommand.parse(_data(**overrides))
    assert exc.value.details["errors"]


def test_missing_reported_at_is_allowed_and_stays_unknown():
    cmd = PublishCommand.parse(_data(reported_at=None))
    assert cmd.reported_at_utc() is None


def test_payload_ignores_actor():
    a = PublishCommand.parse(_data(actor="user_1")).payload()
    b = PublishCommand.parse(_data(actor="user_2")).payload()
    assert a == b


def test_ids_are_sortable_and_sources_deterministic():
    assert len(ulid()) == 26
    assert ulid(now_ms=1, randomness=bytes(10)) < ulid(now_ms=2, randomness=bytes(10))
    name = "central hospital demo"
    assert source_id("inc_1", name) == source_id("inc_1", name)
    assert source_id("inc_1", "a b c d") != source_id("inc_2", "a b c d")
