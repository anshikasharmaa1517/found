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
from found_core.domain.models import Incident
from found_core.services.incidents import RECENT_MAX, IncidentService
from found_core.services.ingest import IngestService
from found_core.services.review import ReviewService
from found_core.services.watch import WatchService
from tests.unit.test_api_handler import call, event

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
OUTSIDER = Caller(user_id="pub_x", groups=frozenset({"publisher"}), org_id="org_x")
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}


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
        Incident(id="inc_1", name="Kesari Valley flood", area="Kesari valley", is_demo=True)
    )
    clock = Clock()
    ingest = IngestService(repo, clock=clock, sleep=lambda _: None)
    watch = WatchService(repo, clock=clock)

    def report(ref, name, claim_type, text):
        claim = ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **HOSPITAL,
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
        "Kesari Valley flood",
        "Kesari valley",
        True,
    )
    with pytest.raises(Forbidden):
        service.details(OUTSIDER, "inc_1")
    with pytest.raises(NotFound):
        service.details(FAMILY, "inc_9")


def test_recent_reports_are_newest_first_with_names_and_sources(world):
    _, service, report, _ = world
    first = report("R-1", "Maya Rawat", "FOUND_SAFE", "Maya Rawat admitted to ward 3.")
    second = report("R-2", "Arjun Negi", "INJURED", "Arjun Negi treated for cuts.")
    recent = service.recent_reports(REVIEWER, "inc_1")
    assert [r.claim.id for r in recent] == [second.id, first.id]
    assert recent[0].subject.display_name == "Arjun Negi"
    assert recent[0].source_name == "Central Hospital Demo" and not recent[0].withheld
    assert len(service.recent_reports(REVIEWER, "inc_1", limit=1)) == 1


def test_the_limit_is_capped(world):
    _, service, report, _ = world
    for n in range(RECENT_MAX + 2):
        report(f"R-{n}", f"Person {n}", "MISSING", f"Person {n} missing.")
    assert len(service.recent_reports(REVIEWER, "inc_1", limit=999)) == RECENT_MAX


def test_an_unreleased_sensitive_report_is_withheld_from_families(world):
    repo, service, report, clock = world
    deceased = report("R-1", "Ramesh Thapliyal", "DECEASED", "Declared dead at 03:20.")
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
    report("R-1", "Ramesh Thapliyal", "DECEASED", "Declared dead at 03:20.")
    family = {"sub": "fam_1", "cognito:groups": "[family]"}

    status, body, _ = call(event("GET", "/v1/incidents/inc_1", claims=family))
    assert status == 200
    assert body == {
        "id": "inc_1",
        "name": "Kesari Valley flood",
        "area": "Kesari valley",
        "is_demo": True,
        "started_at": None,
    }

    status, body, _ = call(event("GET", "/v1/incidents/inc_1/recent", claims=family))
    (item,) = body["reports"]
    assert status == 200 and item["withheld"] is True
    assert "claim_type" not in item and "excerpt" not in item and "source" not in item
    assert item["subject_name"] == "Ramesh Thapliyal"

    bad = call(event("GET", "/v1/incidents/inc_1/recent", claims=family, query={"limit": "x"}))
    assert bad[0] == 400
