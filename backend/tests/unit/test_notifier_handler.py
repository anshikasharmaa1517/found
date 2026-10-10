from datetime import UTC, datetime

import pytest

from found_core import container
from found_core.adapters.dynamodb import alert_item
from found_core.domain.enums import DeliveryStatus
from found_core.domain.models import Alert
from found_core.services.notify import NotifyResult
from handlers import notifier
from tests.unit.test_events import _modify
from tests.unit.test_watcher_handler import Context, bus_event

WHEN = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def alert(status: str) -> dict:
    return alert_item(
        Alert(
            id="alr_1",
            incident_id="inc_1",
            subject_id="per_1",
            subscription_id="sub_1",
            claim_id="clm_1",
            user_id="fam_1",
            relation="UPDATE",
            severity="info",
            message="Newer report for Maya Rawat.",
            delivery_status=status,
            created_at=WHEN,
        )
    )


class Recorder:
    def __init__(self):
        self.calls = []

    def deliver(self, subscription_id, claim_id):
        self.calls.append((subscription_id, claim_id))
        return NotifyResult(claim_id, subscription_id, DeliveryStatus.SENT, sent=["email"])


@pytest.fixture
def recorder(monkeypatch):
    service = Recorder()
    monkeypatch.setattr(container, "notify_service", lambda: service)
    return service


def released_event():
    evt = bus_event({})
    evt["detail"] = _modify(alert("HELD"), alert("PENDING"))
    return evt


def test_a_pending_alert_insert_is_delivered(recorder):
    result = notifier.handler(bus_event(alert("PENDING")), Context())
    assert recorder.calls == [("sub_1", "clm_1")]
    assert result == {"status": "SENT", "sent": ["email"], "note": None, "skipped_reason": None}


def test_a_released_alert_is_delivered(recorder):
    notifier.handler(released_event(), Context())
    assert recorder.calls == [("sub_1", "clm_1")]


@pytest.mark.parametrize("status", ["HELD", "NOT_REQUIRED"])
def test_alerts_that_are_not_due_are_ignored(recorder, status):
    assert notifier.handler(bus_event(alert(status)), Context()) == {"status": "ignored"}
    assert recorder.calls == []


def test_events_from_elsewhere_are_ignored(recorder):
    assert notifier.handler(bus_event({}, source="elsewhere"), Context()) == {"status": "ignored"}
