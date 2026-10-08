from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import DeliveryStatus, Relation, ReviewItemType, Severity
from found_core.domain.models import Subscription
from found_core.services.ingest import IngestService
from found_core.services.watch import WatchService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
T1 = "2026-10-02T21:10:00+05:30"
T2 = "2026-10-03T07:40:00+05:30"
T0 = "2026-10-02T09:00:00+05:30"


class World:
    def __init__(self) -> None:
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.ingest = IngestService(self.repo, clock=FixedClock(), sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=FixedClock())
        self.refs = 0
        self.subject_id = self.report(
            claim_type="MISSING", subject={"type": "PERSON", "new": {"name": "Maya Rawat"}}
        ).subject_id

    def report(self, org=POLICE, claim_type="MISSING", reported_at=T1, subject=None):
        self.refs += 1
        data = {
            "incident_id": "inc_1",
            **org,
            "actor": "user_1",
            "subject": subject or {"type": "PERSON", "id": self.subject_id},
            "claim_type": claim_type,
            "original_text": f"Report {self.refs} about Maya Rawat.",
            "external_reference": f"REF-{self.refs}",
            "reported_at": reported_at,
        }
        return self.ingest.publish(PublishCommand.parse(data)).claim

    def follow(self, sub_id, sms=False, active=True):
        self.repo.add_subscription(
            Subscription(
                id=sub_id,
                subject_id=self.subject_id,
                user_id=f"user_{sub_id}",
                channel_sms=sms,
                active=active,
            )
        )

    def run(self, claim):
        return self.watch.on_claim_created(claim.subject_id, claim.id, claim.seq)

    def first_claim(self):
        return self.repo.list_subject_claims(self.subject_id)[0]

    def alerts_for(self, claim):
        return [a for a in self.repo.alerts.values() if a.claim_id == claim.id]


@pytest.fixture
def world():
    w = World()
    w.follow("sub_a", sms=True)
    w.follow("sub_b")
    w.follow("sub_gone", active=False)
    return w


def test_first_report_alerts_each_active_follower(world):
    result = world.run(world.first_claim())
    assert result.relation == Relation.FIRST
    assert result.alerts_created == 2
    alerts = {a.subscription_id: a for a in world.alerts_for(world.first_claim())}
    assert set(alerts) == {"sub_a", "sub_b"}
    assert alerts["sub_a"].delivery_status == DeliveryStatus.PENDING
    assert alerts["sub_b"].delivery_status == DeliveryStatus.NOT_REQUIRED
    alert = alerts["sub_a"]
    assert alert.user_id == "user_sub_a" and alert.incident_id == "inc_1"
    expected = "First report for Maya Rawat: District Police Demo says missing"
    assert alert.message.startswith(expected)
    assert "Earlier reports are retained." in alert.message


def test_duplicate_delivery_creates_nothing_new(world):
    claim = world.first_claim()
    world.run(claim)
    again = world.run(claim)
    assert again.alerts_created == 0 and again.review_items_created == []
    assert len(world.repo.alerts) == 2


def test_newer_different_status_is_an_update(world):
    world.run(world.first_claim())
    found = world.report(org=HOSPITAL, claim_type="FOUND_SAFE", reported_at=T2)
    result = world.run(found)
    assert result.relation == Relation.UPDATE and result.alerts_created == 2
    message = world.alerts_for(found)[0].message
    assert message.startswith("Newer report for Maya Rawat: Central Hospital Demo says found safe")


def test_repeat_of_same_status_does_not_alert(world):
    repeat = world.report(org=HOSPITAL, claim_type="MISSING", reported_at=T2)
    result = world.run(repeat)
    assert result.relation == Relation.UPDATE and result.alerts_created == 0


def test_late_earlier_report_is_historical(world):
    world.report(org=HOSPITAL, claim_type="FOUND_SAFE", reported_at=T2)
    late = world.report(claim_type="INJURED", reported_at=T0)
    result = world.run(late)
    assert result.relation == Relation.HISTORICAL
    alert = world.alerts_for(late)[0]
    assert alert.message.startswith("Earlier report received for Maya Rawat")
    assert alert.severity == Severity.HIGH


def test_conflict_at_same_time_alerts_high_and_queues_one_review(world):
    clash = world.report(org=HOSPITAL, claim_type="FOUND_SAFE", reported_at=T1)
    result = world.run(clash)
    assert result.relation == Relation.NEEDS_REVIEW
    assert result.review_items_created == [ReviewItemType.CONFLICT]
    assert {a.severity for a in world.alerts_for(clash)} == {Severity.HIGH}
    (item,) = world.repo.review_items.values()
    assert item.ref_id == clash.id and item.subject_id == world.subject_id
    assert item.priority == 2 and item.status == "OPEN"
    assert world.run(clash).review_items_created == []
    assert len(world.repo.review_items) == 1


def test_conflict_is_queued_even_without_followers():
    w = World()
    clash = w.report(org=HOSPITAL, claim_type="FOUND_SAFE", reported_at=T1)
    result = w.run(clash)
    assert result.alerts_created == 0
    assert result.review_items_created == [ReviewItemType.CONFLICT]


def test_deceased_is_held_with_gentle_text_and_one_review(world):
    world.run(world.first_claim())
    deceased = world.report(org=HOSPITAL, claim_type="DECEASED", reported_at=T2)
    result = world.run(deceased)
    assert result.review_items_created == [ReviewItemType.HELD_ALERT]
    alerts = world.alerts_for(deceased)
    assert len(alerts) == 2
    for alert in alerts:
        assert alert.delivery_status == DeliveryStatus.HELD
        assert alert.held_reason == "SENSITIVE_STATUS"
        assert "deceased" not in alert.message.lower()
        assert "coordinator will contact you" in alert.message
    (item,) = world.repo.review_items.values()
    assert item.item_type == ReviewItemType.HELD_ALERT and item.priority == 1


def test_non_status_claim_does_nothing(world):
    seen = world.report(claim_type="SEEN_AT_LOCATION", reported_at=T2)
    result = world.run(seen)
    assert result.relation == Relation.NOT_STATUS
    assert result.alerts_created == 0 and world.repo.review_items == {}


def test_out_of_order_delivery_gives_the_same_alerts(world):
    found = world.report(org=HOSPITAL, claim_type="FOUND_SAFE", reported_at=T2)
    world.run(found)
    world.run(world.first_claim())
    relations = {a.claim_id: a.relation for a in world.repo.alerts.values()}
    assert relations == {world.first_claim().id: Relation.FIRST, found.id: Relation.UPDATE}


def test_retry_after_crash_completes_missing_review(world):
    deceased = world.report(org=HOSPITAL, claim_type="DECEASED", reported_at=T2)
    world.run(deceased)
    world.repo.review_items.clear()
    result = world.run(deceased)
    assert result.alerts_created == 0
    assert result.review_items_created == [ReviewItemType.HELD_ALERT]


def test_claim_removed_by_reset_is_skipped(world):
    result = world.watch.on_claim_created(world.subject_id, "clm_gone", 9)
    assert result.skipped_reason == "CLAIM_NOT_FOUND" and world.repo.alerts == {}


def test_event_that_disagrees_with_the_table_fails_loudly(world):
    with pytest.raises(ValueError):
        world.watch.on_claim_created(world.subject_id, "clm_other", 1)
