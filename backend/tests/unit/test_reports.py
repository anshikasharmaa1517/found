from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.errors import Forbidden, NotFound, ValidationFailed
from found_core.domain.models import Organization
from found_core.services.ingest import IngestService
from found_core.services.reports import ReportService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


HOSPITAL = Organization(
    id="org_h",
    incident_id="inc_1",
    name="Central Hospital Demo",
    name_norm="central hospital demo",
    org_type="HOSPITAL",
)
PUBLISHER = Caller(user_id="user_1", groups=frozenset({"publisher"}), org_id="org_h")

BODY = {
    "subject": {"type": "PERSON", "new": {"name": "Maya Rawat", "age": 24}},
    "claim_type": "MISSING",
    "original_text": "Maya Rawat, 24, missing since the bridge collapse.",
    "external_reference": "CH-1",
    "reported_at": "2026-10-02T21:10:00+05:30",
}


@pytest.fixture
def repo():
    r = InMemoryFoundRepository()
    r.add_incident("inc_1")
    r.add_incident("inc_2")
    r.add_organization(HOSPITAL)
    return r


@pytest.fixture
def service(repo):
    return ReportService(repo, IngestService(repo, clock=FixedClock(), sleep=lambda _: None))


def test_publisher_publishes_as_their_organization(service, repo):
    result = service.publish(PUBLISHER, "inc_1", dict(BODY))
    assert not result.replayed
    assert result.publisher == HOSPITAL
    claim = result.claim
    assert claim.created_by == "user_1"
    source = repo.sources[claim.source_id]
    assert source.name == "Central Hospital Demo" and source.organization_id == "org_h"
    assert source.source_type == "HOSPITAL"


def test_retry_replays(service):
    first = service.publish(PUBLISHER, "inc_1", dict(BODY))
    again = service.publish(PUBLISHER, "inc_1", dict(BODY))
    assert again.replayed and again.claim.id == first.claim.id


@pytest.mark.parametrize(
    "caller",
    [
        Caller(user_id="u", groups=frozenset({"family"}), org_id="org_h"),
        Caller(user_id="u", groups=frozenset({"reviewer", "admin"}), org_id="org_h"),
        Caller(user_id="u", groups=frozenset({"publisher"}), org_id=None),
    ],
)
def test_non_publishers_are_forbidden(service, caller):
    with pytest.raises(Forbidden):
        service.publish(caller, "inc_1", dict(BODY))


def test_org_not_registered_for_incident_is_forbidden(service):
    with pytest.raises(Forbidden):
        service.publish(PUBLISHER, "inc_2", dict(BODY))


def test_unknown_incident_is_not_found(service):
    with pytest.raises(NotFound):
        service.publish(PUBLISHER, "inc_missing", dict(BODY))


@pytest.mark.parametrize("field", ["org_id", "org_name", "org_type", "actor", "extraction_method"])
def test_identity_fields_in_body_are_rejected(service, repo, field):
    with pytest.raises(ValidationFailed) as err:
        service.publish(PUBLISHER, "inc_1", {**BODY, field: "x"})
    assert err.value.details["errors"][0]["field"] == field
    assert repo.claims == {}


def test_invalid_body_is_validation_failed(service):
    with pytest.raises(ValidationFailed):
        service.publish(PUBLISHER, "inc_1", {**BODY, "claim_type": "ROAD_BLOCKED"})
