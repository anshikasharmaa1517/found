from datetime import UTC, datetime

import pytest
from boto3.dynamodb.types import TypeSerializer

from found_core import container
from found_core.adapters.dynamodb import claim_item, subject_item
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.commands import PublishCommand
from found_core.domain.models import Subscription
from found_core.events import EVENT_DETAIL_TYPE, EVENT_SOURCE
from found_core.services.ingest import IngestService
from found_core.services.watch import WatchService
from handlers import watcher


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class Context:
    function_name = "watcher"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:watcher"
    aws_request_id = "req-1"


_serializer = TypeSerializer()


def bus_event(item, source=EVENT_SOURCE):
    image = {k: _serializer.serialize(v) for k, v in item.items()}
    return {
        "id": "evt-bus-1",
        "source": source,
        "detail-type": EVENT_DETAIL_TYPE,
        "detail": {
            "eventID": "evt-1",
            "eventName": "INSERT",
            "dynamodb": {"ApproximateCreationDateTime": 1791195322, "NewImage": image},
        },
    }


@pytest.fixture
def stored(monkeypatch):
    repo = InMemoryFoundRepository()
    repo.add_incident("inc_1")
    ingest = IngestService(repo, clock=FixedClock(), sleep=lambda _: None)
    claim = ingest.publish(
        PublishCommand.parse(
            {
                "incident_id": "inc_1",
                "org_id": "org_p",
                "org_name": "District Police Demo",
                "org_type": "POLICE",
                "actor": "user_1",
                "subject": {"type": "PERSON", "new": {"name": "Maya Rawat"}},
                "claim_type": "MISSING",
                "original_text": "Maya Rawat missing.",
                "external_reference": "REF-1",
                "reported_at": "2026-10-02T21:10:00+05:30",
            }
        )
    ).claim
    repo.add_subscription(Subscription(id="sub_1", subject_id=claim.subject_id, user_id="fam"))
    service = WatchService(repo, clock=FixedClock())
    monkeypatch.setattr(container, "watch_service", lambda: service)
    return repo, claim


def test_claim_event_creates_alert(stored):
    repo, claim = stored
    result = watcher.handler(bus_event(claim_item(claim)), Context())
    assert result == {
        "status": "watched",
        "relation": "FIRST",
        "alerts_created": 1,
        "review_items_created": [],
        "skipped_reason": None,
    }
    assert len(repo.alerts) == 1


def test_other_entities_and_foreign_events_are_ignored(stored):
    repo, claim = stored
    subject = repo.get_subject(claim.subject_id)
    assert watcher.handler(bus_event(subject_item(subject)), Context())["status"] == "ignored"
    foreign = bus_event(claim_item(claim), source="aws.s3")
    assert watcher.handler(foreign, Context())["status"] == "ignored"
    assert repo.alerts == {}


def test_service_errors_propagate_for_retry(stored, monkeypatch):
    _, claim = stored

    class Broken:
        def on_claim_created(self, *args):
            raise RuntimeError("table unavailable")

    monkeypatch.setattr(container, "watch_service", lambda: Broken())
    with pytest.raises(RuntimeError):
        watcher.handler(bus_event(claim_item(claim)), Context())
