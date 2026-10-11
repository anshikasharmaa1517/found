from datetime import UTC, datetime, timedelta

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import ReviewItemType
from found_core.domain.errors import Forbidden, NotFound
from found_core.domain.ids import review_item_id
from found_core.domain.models import Incident, RiverCourse
from found_core.services.incidents import RECENT_MAX, WITHHELD_KEY, IncidentService
from found_core.services.ingest import IngestService
from found_core.services.review import ReviewService
from found_core.services.watch import WatchService
from tests.unit.test_api_handler import call, event

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
OUTSIDER = Caller(user_id="pub_x", groups=frozenset({"publisher"}), org_id="org_x")
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
RELIEF = {"org_id": "org_r", "org_name": "Flood Relief Demo", "org_type": "NGO"}


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        self.at += timedelta(seconds=1)
        return self.at


@pytest.fixture
def world():
    repo = InMemoryFoundRepository()
    repo.put_incident(
        Incident(id="inc_1", name="Trishuli flood", area="Trishuli Bazar", is_demo=True)
    )
    clock = Clock()
    ingest = IngestService(repo, clock=clock, sleep=lambda _: None)
    watch = WatchService(repo, clock=clock)

    def report(ref, name, claim_type, text, org=HOSPITAL):
        claim = ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": {"type": "PERSON", "new": {"name": name}},
                    "claim_type": claim_type,
                    "original_text": text,
                    "external_reference": ref,
                    "reported_at": "2026-10-03T07:40:00+05:30",
                }
            )
        ).claim
        watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
        return claim

    return repo, IncidentService(repo), report, clock


def test_details_name_the_incident_and_check_access(world):
    repo, service, _, _ = world
    incident = service.details(FAMILY, "inc_1")
    assert (incident.name, incident.area, incident.is_demo) == (
        "Trishuli flood",
        "Trishuli Bazar",
        True,
    )
    with pytest.raises(Forbidden):
        service.details(OUTSIDER, "inc_1")
    with pytest.raises(NotFound):
        service.details(FAMILY, "inc_9")


def test_recent_reports_are_newest_first_with_names_and_sources(world):
    _, service, report, _ = world
    first = report("R-1", "Sita Tamang", "FOUND_SAFE", "Sita Tamang admitted to ward 3.")
    second = report("R-2", "Bikash Shrestha", "INJURED", "Bikash Shrestha treated for cuts.")
    recent = service.recent_reports(REVIEWER, "inc_1")
    assert [r.claim.id for r in recent] == [second.id, first.id]
    assert recent[0].subject.display_name == "Bikash Shrestha"
    assert recent[0].source_name == "Central Hospital Demo" and not recent[0].withheld
    assert len(service.recent_reports(REVIEWER, "inc_1", limit=1)) == 1


def test_the_limit_is_capped(world):
    _, service, report, _ = world
    for n in range(RECENT_MAX + 2):
        report(f"R-{n}", f"Person {n}", "MISSING", f"Person {n} missing.")
    assert len(service.recent_reports(REVIEWER, "inc_1", limit=999)) == RECENT_MAX


def test_an_unreleased_sensitive_report_is_withheld_from_families(world):
    repo, service, report, clock = world
    deceased = report("R-1", "Gopal Adhikari", "DECEASED", "Declared dead at 03:20.")
    (mine,) = service.recent_reports(FAMILY, "inc_1")
    assert mine.withheld
    (theirs,) = service.recent_reports(REVIEWER, "inc_1")
    assert not theirs.withheld

    ReviewService(repo, CursorCodec(b"k" * 32), clock=clock).resolve(
        REVIEWER, "inc_1", review_item_id(ReviewItemType.HELD_ALERT, deceased.id), {}
    )
    (released,) = service.recent_reports(FAMILY, "inc_1")
    assert not released.withheld


def test_routes_show_details_and_mask_withheld_reports(world, monkeypatch):
    _, service, report, _ = world
    monkeypatch.setattr(container, "incident_service", lambda: service)
    report("R-1", "Gopal Adhikari", "DECEASED", "Declared dead at 03:20.")
    family = {"sub": "fam_1", "cognito:groups": "[family]"}

    status, body, _ = call(event("GET", "/v1/incidents/inc_1", claims=family))
    assert status == 200
    assert body == {
        "id": "inc_1",
        "name": "Trishuli flood",
        "area": "Trishuli Bazar",
        "is_demo": True,
        "started_at": None,
        "river": None,
    }

    status, body, _ = call(event("GET", "/v1/incidents/inc_1/recent", claims=family))
    (item,) = body["reports"]
    assert status == 200 and item["withheld"] is True
    assert "claim_type" not in item and "excerpt" not in item and "source" not in item
    assert item["subject_name"] == "Gopal Adhikari"

    bad = call(event("GET", "/v1/incidents/inc_1/recent", claims=family, query={"limit": "x"}))
    assert bad[0] == 400


def test_sources_are_busiest_first_with_counts_and_relays(world):
    _, service, report, _ = world
    report("R-1", "Sita Tamang", "FOUND_SAFE", "Sita Tamang admitted to ward 3.")
    report("R-2", "Bikash Shrestha", "INJURED", "Bikash Shrestha treated for cuts.")
    relay = report(
        "V-1",
        "Sita Tamang",
        "FOUND_SAFE",
        "According to Central Hospital Demo, Sita Tamang is safe.",
        org=RELIEF,
    )
    hospital, relief = service.sources(REVIEWER, "inc_1")
    assert (hospital.source.name, hospital.reports, hospital.cited_by) == (
        "Central Hospital Demo",
        2,
        1,
    )
    assert hospital.by_type == {"FOUND_SAFE": 1, "INJURED": 1}
    assert (relief.reports, relief.cited_by) == (1, 0)
    assert relief.latest_at == relay.ingested_at
    assert hospital.latest_at < relay.ingested_at


def test_recent_reports_can_come_from_one_source(world):
    _, service, report, _ = world
    report("R-1", "Sita Tamang", "FOUND_SAFE", "Sita Tamang admitted to ward 3.")
    relay = report("V-1", "Bikash Shrestha", "MISSING", "Bikash Shrestha not found.", org=RELIEF)
    (only,) = service.recent_reports(REVIEWER, "inc_1", source_id=relay.source_id)
    assert only.claim.id == relay.id
    assert service.recent_reports(REVIEWER, "inc_1", source_id="src_none") == []


def test_source_counts_hide_the_type_of_held_reports(world):
    _, service, report, _ = world
    report("R-1", "Gopal Adhikari", "DECEASED", "Declared dead at 03:20.")
    (mine,) = service.sources(FAMILY, "inc_1")
    assert mine.by_type == {WITHHELD_KEY: 1}
    (theirs,) = service.sources(REVIEWER, "inc_1")
    assert theirs.by_type == {"DECEASED": 1}
    with pytest.raises(Forbidden):
        service.sources(OUTSIDER, "inc_1")


def test_sources_route_lists_each_source(world, monkeypatch):
    _, service, report, _ = world
    monkeypatch.setattr(container, "incident_service", lambda: service)
    claim = report("R-1", "Sita Tamang", "FOUND_SAFE", "Sita Tamang admitted to ward 3.")
    family = {"sub": "fam_1", "cognito:groups": "[family]"}

    status, body, _ = call(event("GET", "/v1/incidents/inc_1/sources", claims=family))
    assert status == 200
    assert body == {
        "sources": [
            {
                "id": claim.source_id,
                "name": "Central Hospital Demo",
                "source_type": "HOSPITAL",
                "organization_id": "org_h",
                "reports": 1,
                "by_type": {"FOUND_SAFE": 1},
                "cited_by": 0,
                "latest_at": "2026-10-05T10:15:01Z",
            }
        ]
    }

    status, body, _ = call(
        event(
            "GET",
            "/v1/incidents/inc_1/recent",
            claims=family,
            query={"source_id": "src_none"},
        )
    )
    assert status == 200 and body == {"reports": []}


def test_the_route_returns_the_river_course(world, monkeypatch):
    repo, service, _, _ = world
    monkeypatch.setattr(container, "incident_service", lambda: service)
    river = RiverCourse(
        name="Trishuli river",
        note="Flooded on 26 August 2026.",
        attribution="OpenStreetMap contributors",
        coordinates=((85.15, 27.93), (85.14, 27.92)),
    )
    repo.put_incident(
        Incident(id="inc_1", name="Trishuli flood", area="Trishuli Bazar", river=river)
    )
    family = {"sub": "fam_1", "cognito:groups": "[family]"}
    status, body, _ = call(event("GET", "/v1/incidents/inc_1", claims=family))
    assert status == 200
    assert body["river"] == {
        "name": "Trishuli river",
        "note": "Flooded on 26 August 2026.",
        "attribution": "OpenStreetMap contributors",
        "coordinates": [[85.15, 27.93], [85.14, 27.92]],
    }


@pytest.mark.parametrize(
    "coordinates",
    [((85.15, 27.93),), ((85.15, 27.93), (185.0, 27.9)), ((85.15, 27.93), (85.1, -91.0))],
)
def test_a_river_needs_two_points_on_the_globe(coordinates):
    with pytest.raises(ValueError):
        RiverCourse(name="R", note="N", attribution="A", coordinates=coordinates)
