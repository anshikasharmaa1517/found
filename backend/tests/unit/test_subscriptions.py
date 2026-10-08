from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import DeliveryStatus
from found_core.domain.errors import BadRequest, Forbidden, NotFound, ValidationFailed
from found_core.domain.models import Alert
from found_core.services.ingest import IngestService
from found_core.services.subscriptions import SubscriptionService
from found_core.services.watch import WatchService


class FixedClock:
    def __init__(self) -> None:
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
OTHER_FAMILY = Caller(user_id="fam_2", groups=frozenset({"family"}))
REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))


class World:
    def __init__(self) -> None:
        self.clock = FixedClock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=self.clock)
        self.service = SubscriptionService(self.repo, CursorCodec(b"k" * 32), clock=self.clock)
        self.refs = 0
        self.person_id = self.report("MISSING", "2026-10-02T21:10:00+05:30", new=True)

    def report(self, claim_type, reported_at, new=False, org="District Police Demo"):
        self.refs += 1
        subject = (
            {"type": "PERSON", "new": {"name": "Maya Rawat"}}
            if new
            else {"type": "PERSON", "id": self.person_id}
        )
        claim = self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    "org_id": f"org_{org[:3].lower()}",
                    "org_name": org,
                    "org_type": "HOSPITAL",
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": claim_type,
                    "original_text": f"Report {self.refs} about Maya Rawat.",
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": reported_at,
                }
            )
        ).claim
        self.watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
        return claim.subject_id


@pytest.fixture
def world():
    return World()


def test_follow_creates_one_subscription_with_channels(world):
    result = world.service.follow(
        FAMILY, world.person_id, {"channel_sms": True, "phone_e164": "+919876543210"}
    )
    assert result.created
    sub = result.subscription
    assert sub.user_id == "fam_1" and sub.subject_id == world.person_id
    assert sub.channel_sms and not sub.channel_email and sub.active
    assert sub.created_at == world.clock.at


def test_following_again_updates_channels_instead_of_duplicating(world):
    first = world.service.follow(FAMILY, world.person_id, {}).subscription
    world.clock.at += timedelta(hours=1)
    again = world.service.follow(
        FAMILY, world.person_id, {"channel_email": True, "email": "asha@example.org"}
    )
    assert not again.created
    assert again.subscription.id == first.id
    assert again.subscription.channel_email
    assert again.subscription.created_at == first.created_at
    assert len(world.repo.subscriptions) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"channel_sms": True},
        {"channel_sms": True, "phone_e164": "9876543210"},
        {"channel_email": True},
        {"channel_email": True, "email": "not-an-email"},
        {"channel_push": True},
        {"user_id": "someone_else"},
    ],
)
def test_invalid_channels_are_422(world, body):
    with pytest.raises(ValidationFailed):
        world.service.follow(FAMILY, world.person_id, body)


def test_only_family_can_follow(world):
    with pytest.raises(Forbidden):
        world.service.follow(REVIEWER, world.person_id, {})


def test_unknown_person_is_not_found(world):
    with pytest.raises(NotFound):
        world.service.follow(FAMILY, "per_missing", {})


def test_unfollow_deactivates_and_forgets_contact_details(world):
    sub = world.service.follow(
        FAMILY, world.person_id, {"channel_sms": True, "phone_e164": "+919876543210"}
    ).subscription
    world.service.unfollow(FAMILY, sub.id)
    stored = world.repo.subscriptions[sub.id]
    assert not stored.active and not stored.channel_sms and stored.phone_e164 is None
    assert world.service.my_subscriptions(FAMILY) == []
    world.service.unfollow(FAMILY, sub.id)
    assert world.service.follow(FAMILY, world.person_id, {}).created


def test_cannot_unfollow_someone_elses_subscription(world):
    sub = world.service.follow(FAMILY, world.person_id, {}).subscription
    with pytest.raises(NotFound):
        world.service.unfollow(OTHER_FAMILY, sub.id)
    assert world.repo.subscriptions[sub.id].active


def test_followers_get_alerts_in_their_feed_and_nobody_elses(world):
    world.service.follow(FAMILY, world.person_id, {})
    world.report("FOUND_SAFE", "2026-10-03T07:40:00+05:30", org="Central Hospital Demo")
    page = world.service.alert_feed(FAMILY)
    assert len(page.alerts) == 1
    alert = page.alerts[0]
    assert alert.message.startswith("Newer report for Maya Rawat: Central Hospital Demo")
    assert alert.delivery_status == DeliveryStatus.NOT_REQUIRED
    assert page.next_cursor is None
    assert world.service.alert_feed(OTHER_FAMILY).alerts == []


def _alert(n: int, user_id: str = "fam_1") -> Alert:
    return Alert(
        id=f"alr_{n:02d}",
        incident_id="inc_1",
        subject_id="per_1",
        subscription_id="sub_1",
        claim_id=f"clm_{n}",
        user_id=user_id,
        relation="UPDATE",
        severity="info",
        message=f"Alert {n}",
        delivery_status="NOT_REQUIRED",
        created_at=datetime(2026, 10, 5, tzinfo=UTC) + timedelta(minutes=n),
    )


def test_feed_is_newest_first_and_pages(world):
    for n in range(5):
        world.repo.put_alert_if_absent(_alert(n))
    first = world.service.alert_feed(FAMILY, limit="2")
    assert [a.id for a in first.alerts] == ["alr_04", "alr_03"]
    second = world.service.alert_feed(FAMILY, limit="2", cursor=first.next_cursor)
    assert [a.id for a in second.alerts] == ["alr_02", "alr_01"]
    third = world.service.alert_feed(FAMILY, limit="2", cursor=second.next_cursor)
    assert [a.id for a in third.alerts] == ["alr_00"] and third.next_cursor is None


def test_feed_cursor_cannot_be_used_by_another_user(world):
    for n in range(3):
        world.repo.put_alert_if_absent(_alert(n))
    first = world.service.alert_feed(FAMILY, limit="1")
    with pytest.raises(BadRequest):
        world.service.alert_feed(OTHER_FAMILY, limit="1", cursor=first.next_cursor)


def test_feed_is_family_only(world):
    with pytest.raises(Forbidden):
        world.service.alert_feed(REVIEWER)
