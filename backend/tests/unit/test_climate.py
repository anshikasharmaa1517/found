from datetime import UTC, datetime

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.climate import CAVEAT, build_feature
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import SubjectType
from found_core.domain.errors import Forbidden, NotFound
from found_core.services.climate import ClimateService
from found_core.services.ingest import IngestService
from found_core.services.map import MapService
from found_core.services.watch import WatchService
from tests.unit.test_api_handler import call, event

FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
OUTSIDER = Caller(user_id="pub_x", groups=frozenset({"publisher"}), org_id="org_x")
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
VOLUNTEERS = {"org_id": "org_v", "org_name": "Valley Volunteers Demo", "org_type": "COMMUNITY"}
BRIDGE = {"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354}
GHAT = {"name": "Market Ghat", "lat": 30.7231, "lon": 78.4302}


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


class World:
    def __init__(self):
        self.clock = Clock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=self.clock)
        self.climate = ClimateService(self.repo, clock=self.clock)
        self.ids: dict[str, str] = {}
        self.refs = 0

    def report(self, key, kind, name, claim_type, at, org=POLICE, where=None):
        self.refs += 1
        subject = (
            {"type": kind, "id": self.ids[key]}
            if key in self.ids
            else {"type": kind, "new": {"name": name}}
        )
        claim = self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": claim_type,
                    "original_text": f"{name}: {claim_type.lower().replace('_', ' ')}.",
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": at,
                    **({"location": where} if where else {}),
                }
            )
        ).claim
        self.ids.setdefault(key, claim.subject_id)
        self.watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
        return claim

    def feature(self, key):
        return next(
            f for f in self.climate.layer(FAMILY, "inc_1").features if f.subject.id == self.ids[key]
        )


@pytest.fixture
def world():
    return World()


def test_disagreeing_bridge_reports_both_stay_visible_and_are_flagged(world):
    closed = world.report(
        "bridge",
        "INFRASTRUCTURE",
        "Old Bridge",
        "BRIDGE_DAMAGED",
        "2026-10-02T20:10:00+05:30",
        where=BRIDGE,
    )
    opened = world.report(
        "bridge",
        "INFRASTRUCTURE",
        "Old Bridge",
        "BRIDGE_OPEN",
        "2026-10-03T08:15:00+05:30",
        org=VOLUNTEERS,
        where=BRIDGE,
    )
    feature = world.feature("bridge")
    assert feature.label == "Reported bridge open" and feature.cited_claim_id == opened.id
    assert [(r.claim.id, r.source_name) for r in feature.conflicts] == [
        (closed.id, "District Police Demo")
    ]
    assert [r.claim.id for r in feature.recent] == [opened.id, closed.id]
    assert feature.location.name == "Old Bridge" and feature.report_count == 2
    # A dated newer report is an update, not a puzzle for a reviewer; it is still flagged.
    assert not feature.needs_review


def test_types_without_status_are_labelled_as_the_latest_report(world):
    world.report(
        "river", "HAZARD", "Kesari river", "WATER_RISING", "2026-10-02T19:45:00+05:30", where=GHAT
    )
    latest = world.report(
        "river",
        "HAZARD",
        "Kesari river",
        "WATER_RECEDING",
        "2026-10-03T06:30:00+05:30",
        org=VOLUNTEERS,
    )
    feature = world.feature("river")
    assert feature.label == "Latest report: water receding"
    assert feature.basis.startswith("Latest report;") and feature.cited_claim_id == latest.id
    assert feature.conflicts == [] and not feature.needs_review
    # The newest report has no place, so the place comes from the newest located one.
    assert feature.location.name == "Market Ghat"


def test_a_subject_without_reports_is_labelled_plainly():
    from found_core.domain.models import Subject

    subject = Subject(
        id="aid_1",
        incident_id="inc_1",
        subject_type=SubjectType.AID_POINT,
        display_name="Ghat aid point",
        name_norm="ghat aid point",
    )
    feature = build_feature(subject, [], {}, {})
    assert (feature.label, feature.cited_claim_id, feature.location) == ("No reports", None, None)


def test_people_are_not_in_the_climate_layer_and_climate_is_not_in_people_counts(world):
    world.report(
        "maya", "PERSON", "Maya Rawat", "MISSING", "2026-10-02T21:10:00+05:30", where=BRIDGE
    )
    world.report(
        "bridge",
        "INFRASTRUCTURE",
        "Old Bridge",
        "BRIDGE_DAMAGED",
        "2026-10-02T20:10:00+05:30",
        where=BRIDGE,
    )
    features = world.climate.layer(FAMILY, "inc_1").features
    assert [f.subject.subject_type for f in features] == [SubjectType.INFRASTRUCTURE]
    counts = MapService(world.repo, clock=world.clock).incident_map(FAMILY, "inc_1").counts
    (place,) = counts.places
    assert place.reports == 1 and place.by_status["MISSING"] == 1


def test_the_layer_is_cached_briefly_and_access_is_checked_each_time(world):
    world.report(
        "bridge", "INFRASTRUCTURE", "Old Bridge", "BRIDGE_DAMAGED", "2026-10-02T20:10:00+05:30"
    )
    first = world.climate.layer(FAMILY, "inc_1")
    world.report(
        "shelter", "SHELTER", "Riverside Shelter", "SHELTER_OPEN", "2026-10-02T22:00:00+05:30"
    )
    assert world.climate.layer(FAMILY, "inc_1") is first
    world.clock.at = world.clock.at.replace(minute=16)
    assert len(world.climate.layer(FAMILY, "inc_1").features) == 2
    with pytest.raises(Forbidden):
        world.climate.layer(OUTSIDER, "inc_1")
    with pytest.raises(NotFound):
        world.climate.layer(FAMILY, "inc_9")


def test_the_demo_dataset_has_a_sourced_climate_picture():
    from found_core.fixtures import load_dataset
    from tests.unit.test_dataset import read_dataset

    repo = InMemoryFoundRepository()
    dataset = read_dataset()
    load_dataset(dataset, repo, IngestService(repo, sleep=lambda _: None))
    layer = ClimateService(repo).layer(FAMILY, "inc_demo")
    by_name = {f.subject.display_name: f for f in layer.features}
    assert set(by_name) >= {"Old Bridge", "Riverside Shelter", "Kesari river at Market Ghat"}
    bridge = by_name["Old Bridge"]
    assert bridge.label == "Reported bridge open" and len(bridge.conflicts) == 1
    assert all(f.location is not None for f in layer.features)


def test_the_climate_route_returns_features_with_sources(monkeypatch):
    world = World()
    world.report(
        "bridge",
        "INFRASTRUCTURE",
        "Old Bridge",
        "BRIDGE_DAMAGED",
        "2026-10-02T20:10:00+05:30",
        where=BRIDGE,
    )
    world.report(
        "bridge",
        "INFRASTRUCTURE",
        "Old Bridge",
        "BRIDGE_OPEN",
        "2026-10-03T08:15:00+05:30",
        org=VOLUNTEERS,
        where=BRIDGE,
    )
    monkeypatch.setattr(container, "climate_service", lambda: world.climate)
    status, body, _ = call(
        event(
            "GET", "/v1/incidents/inc_1/climate", claims={"sub": "f", "cognito:groups": "[family]"}
        )
    )
    assert status == 200 and body["caveat"] == CAVEAT
    (feature,) = body["features"]
    assert feature["subject_type"] == "INFRASTRUCTURE" and feature["name"] == "Old Bridge"
    assert feature["label"] == "Reported bridge open"
    assert feature["location"]["lat"] == 30.7268
    assert feature["conflicts"][0]["source"] == "District Police Demo"
    assert feature["conflicts"][0]["claim_type"] == "BRIDGE_DAMAGED"
    assert [r["source"] for r in feature["recent"]] == [
        "Valley Volunteers Demo",
        "District Police Demo",
    ]
    assert body["updated_at"] == "2026-10-05T10:15:00Z"
