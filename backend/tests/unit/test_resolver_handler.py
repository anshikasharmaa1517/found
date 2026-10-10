import pytest

from found_core import container
from found_core.adapters.dynamodb import subject_item
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.commands import PublishCommand
from found_core.domain.identity import pair_key
from found_core.services.ingest import IngestService
from found_core.services.resolve import ResolveService
from handlers import resolver
from tests.unit.test_watcher_handler import Context, FixedClock, bus_event


@pytest.fixture
def people(monkeypatch):
    repo = InMemoryFoundRepository()
    repo.add_incident("inc_1")
    ingest = IngestService(repo, clock=FixedClock(), sleep=lambda _: None)
    ids = []
    for ref in ("P-1", "P-2"):
        claim = ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    "org_id": "org_p",
                    "org_name": "District Police Demo",
                    "org_type": "POLICE",
                    "actor": "user_1",
                    "subject": {"type": "PERSON", "new": {"name": "Maya Rawat", "age": 24}},
                    "claim_type": "MISSING",
                    "original_text": "Maya Rawat, 24, missing.",
                    "external_reference": ref,
                    "reported_at": "2026-10-02T21:10:00+05:30",
                }
            )
        ).claim
        ids.append(claim.subject_id)
    service = ResolveService(repo, clock=FixedClock())
    monkeypatch.setattr(container, "resolve_service", lambda: service)
    return repo, ids


def test_a_person_insert_creates_the_proposal(people):
    repo, ids = people
    result = resolver.handler(bus_event(subject_item(repo.get_subject(ids[1]))), Context())
    assert result["status"] == "resolved" and result["candidates"] == 1
    assert result["proposals_created"] == [pair_key(*ids)]


def test_repeats_and_other_events_change_nothing(people):
    repo, ids = people
    evt = bus_event(subject_item(repo.get_subject(ids[1])))
    resolver.handler(evt, Context())
    assert resolver.handler(evt, Context())["proposals_created"] == []
    assert resolver.handler(bus_event({"entity_type": "OTHER"}), Context()) == {"status": "ignored"}
    assert resolver.handler(bus_event({}, source="elsewhere"), Context()) == {"status": "ignored"}


def test_a_place_insert_is_ignored(people):
    repo, ids = people
    item = {**subject_item(repo.get_subject(ids[0])), "subject_type": "PLACE"}
    assert resolver.handler(bus_event(item), Context()) == {"status": "ignored"}
