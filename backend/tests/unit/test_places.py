from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.errors import Forbidden, NotFound, ReferenceConflict, ValidationFailed
from found_core.domain.models import Location
from found_core.domain.places import CAVEAT, place_counts
from found_core.services.ingest import IngestService
from found_core.services.map import MapService

from .factories import claim

BRIDGE = Location(
    id="loc_bridge", incident_id="inc_1", name="Old Bridge", name_norm="old bridge",
    lat=30.73, lon=78.44,
)  # fmt: skip
CAMP = Location(
    id="loc_camp", incident_id="inc_1", name="Relief Camp", name_norm="relief camp",
    lat=30.70, lon=78.40,
)  # fmt: skip
NAMED_ONLY = Location(
    id="loc_named", incident_id="inc_1", name="Upper Village", name_norm="upper village"
)

T1 = "2026-10-02T15:40:00+00:00"
T2 = "2026-10-03T02:10:00+00:00"


def at(c, location_id):
    return c.model_copy(update={"location_id": location_id})


def test_counts_reports_per_place_by_bucket():
    claims = [
        at(claim(1, "MISSING", T1), "loc_bridge"),
        at(claim(2, "FOUND_SAFE", T2, source_id="src_h"), "loc_bridge"),
        at(
            claim(3, "INJURED", T2).model_copy(
                update={"id": "clm_x", "subject_id": "per_2", "seq": 1}
            ),
            "loc_camp",
        ),
        at(claim(4, "SEEN_AT_LOCATION", None), "loc_bridge"),
    ]
    counts = place_counts(claims, [BRIDGE, CAMP])
    bridge, camp = counts.places
    assert bridge.location == BRIDGE and bridge.reports == 3
    assert bridge.by_status == {"MISSING": 1, "FOUND_SAFE": 1, "NEEDS_REVIEW": 0, "OTHER": 1}
    assert camp.by_status == {"MISSING": 0, "FOUND_SAFE": 0, "NEEDS_REVIEW": 0, "OTHER": 1}
    assert (counts.located_reports, counts.unlocated_reports) == (4, 0)
    assert counts.caveat == CAVEAT


def test_conflicts_count_as_needs_review():
    claims = [
        at(claim(1, "MISSING", T1), "loc_bridge"),
        at(claim(2, "FOUND_SAFE", T1, source_id="src_h"), "loc_bridge"),
    ]
    (bridge,) = place_counts(claims, [BRIDGE]).places
    assert bridge.by_status["MISSING"] == 1 and bridge.by_status["NEEDS_REVIEW"] == 1


def test_deceased_is_not_shown_as_its_own_count():
    (bridge,) = place_counts([at(claim(1, "DECEASED", T1), "loc_bridge")], [BRIDGE]).places
    assert "DECEASED" not in bridge.by_status and bridge.by_status["OTHER"] == 1


def test_reports_without_coordinates_are_counted_as_unlocated():
    claims = [claim(1, "MISSING", T1), at(claim(2, "MISSING", T2), "loc_named")]
    counts = place_counts(claims, [NAMED_ONLY])
    assert counts.places == []
    assert (counts.located_reports, counts.unlocated_reports) == (0, 2)


def test_busiest_place_first():
    claims = [
        at(claim(1, "MISSING", T1), "loc_camp"),
        at(claim(2, "MISSING", T2), "loc_bridge"),
        at(claim(3, "MISSING", T2).model_copy(update={"seq": 3}), "loc_bridge"),
    ]
    assert [p.location.id for p in place_counts(claims, [BRIDGE, CAMP]).places] == [
        "loc_bridge",
        "loc_camp",
    ]


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
REVIEWER = Caller(user_id="rev", groups=frozenset({"reviewer"}))


def cmd(ref, location=None, **overrides):
    return PublishCommand.parse(
        {
            "incident_id": "inc_1",
            **POLICE,
            "actor": "user_1",
            "subject": {"type": "PERSON", "new": {"name": f"Person {ref}"}},
            "claim_type": "MISSING",
            "original_text": "Missing near the old bridge.",
            "external_reference": ref,
            "reported_at": "2026-10-02T21:10:00+05:30",
            **({"location": location} if location is not None else {}),
            **overrides,
        }
    )


@pytest.fixture
def world():
    repo = InMemoryFoundRepository()
    repo.add_incident("inc_1")
    repo.add_incident("inc_2")
    clock = Clock()
    return repo, IngestService(repo, clock=clock, sleep=lambda _: None), clock


BRIDGE_AT = {"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354}


def test_publish_stores_one_location_per_place(world):
    repo, ingest, _ = world
    first = ingest.publish(cmd("R1", BRIDGE_AT)).claim
    again = ingest.publish(cmd("R2", {**BRIDGE_AT, "name": " old  bridge ", "lat": 30.72681})).claim
    assert first.location_id and first.location_id == again.location_id
    (stored,) = repo.locations.values()
    assert (stored.name, stored.lat, stored.lon) == ("Old Bridge", 30.7268, 78.4354)


def test_a_name_alone_is_a_location_without_coordinates(world):
    repo, ingest, _ = world
    claim_ = ingest.publish(cmd("R1", {"name": "Upper Village"})).claim
    assert repo.locations[claim_.location_id].lat is None


def test_location_is_part_of_the_reports_content(world):
    _, ingest, _ = world
    ingest.publish(cmd("R1", BRIDGE_AT))
    assert ingest.publish(cmd("R1", BRIDGE_AT)).replayed
    with pytest.raises(ReferenceConflict):
        ingest.publish(cmd("R1", {**BRIDGE_AT, "name": "Relief Camp"}))


def test_reports_without_location_keep_their_old_hash():
    assert "location" not in cmd("R1").payload()


@pytest.mark.parametrize(
    "location",
    [
        {"name": "", "lat": 1, "lon": 1},
        {"name": "X", "lat": 91, "lon": 1},
        {"name": "X", "lat": 1, "lon": -181},
        {"name": "X", "lat": 1},
        {"name": "X", "lat": float("nan"), "lon": 1},
        {"name": "X", "lat": 1, "lon": 1, "extra": True},
    ],
)
def test_bad_locations_are_rejected(location):
    with pytest.raises(ValidationFailed):
        cmd("R1", location)


def test_map_service_counts_and_caches_for_thirty_seconds(world):
    repo, ingest, clock = world
    ingest.publish(cmd("R1", BRIDGE_AT))
    maps = MapService(repo, clock=clock)
    first = maps.incident_map(REVIEWER, "inc_1")
    assert first.counts.places[0].reports == 1

    ingest.publish(cmd("R2", BRIDGE_AT))
    clock.at += timedelta(seconds=29)
    assert maps.incident_map(REVIEWER, "inc_1") is first

    clock.at += timedelta(seconds=2)
    fresh = maps.incident_map(REVIEWER, "inc_1")
    assert fresh.counts.places[0].reports == 2 and fresh.updated_at == clock.at


def test_map_checks_incident_and_access_even_when_cached(world):
    repo, ingest, clock = world
    maps = MapService(repo, clock=clock)
    maps.incident_map(REVIEWER, "inc_1")
    with pytest.raises(Forbidden):
        maps.incident_map(
            Caller(user_id="p", groups=frozenset({"publisher"}), org_id="org_x"), "inc_1"
        )
    with pytest.raises(NotFound):
        maps.incident_map(REVIEWER, "inc_missing")
