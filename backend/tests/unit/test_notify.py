from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import DeliveryStatus, ReviewItemType
from found_core.domain.ids import review_item_id
from found_core.domain.models import Subscription
from found_core.ports.channels import (
    ChannelDisabled,
    DeliveryRejected,
    DeliveryUnavailable,
    DisabledChannel,
)
from found_core.services.ingest import IngestService
from found_core.services.notify import ATTEMPTS, EMAIL_SUBJECT, HeldNotReleased, NotifyService
from found_core.services.review import ReviewService
from found_core.services.watch import WatchService

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}


class Clock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class FakeChannel:
    def __init__(self, name, failures=()):
        self.name = name
        self.failures = list(failures)
        self.sent = []

    def send(self, to, subject, text):
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append((to, subject, text))


class World:
    def __init__(self, email=None, sms=None):
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.ingest = IngestService(self.repo, clock=Clock(), sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=Clock())
        self.email = email or FakeChannel("email")
        self.sms = sms or FakeChannel("sms")
        self.sleeps = []
        self.notify = NotifyService(
            self.repo, self.email, self.sms, clock=Clock(), sleep=self.sleeps.append
        )
        self.person = None
        self.refs = 0

    def report(self, claim_type, org=POLICE, at="2026-10-02T21:10:00+05:30"):
        self.refs += 1
        subject = (
            {"type": "PERSON", "id": self.person}
            if self.person
            else {"type": "PERSON", "new": {"name": "Maya Rawat"}}
        )
        claim = self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": claim_type,
                    "original_text": f"Report {self.refs} about Maya Rawat.",
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": at,
                }
            )
        ).claim
        self.person = claim.subject_id
        self.watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
        return claim

    def follow(self, sms=False, email=False, active=True, sub_id="sub_1"):
        self.repo.add_subscription(
            Subscription(
                id=sub_id,
                subject_id=self.person,
                user_id="fam_1",
                channel_sms=sms,
                channel_email=email,
                phone_e164="+919876543210" if sms else None,
                email="family@example.com" if email else None,
                active=active,
            )
        )

    def alert(self, claim, sub_id="sub_1"):
        return self.repo.get_alert(sub_id, claim.id)


def update(world, **follow):
    world.report("MISSING")
    world.follow(**follow)
    return world.report("FOUND_SAFE", org=HOSPITAL, at="2026-10-03T07:40:00+05:30")


def test_an_email_alert_is_sent_once_and_marked_sent():
    world = World()
    claim = update(world, email=True)
    assert world.alert(claim).delivery_status == DeliveryStatus.PENDING

    result = world.notify.deliver("sub_1", claim.id)
    assert result.status == DeliveryStatus.SENT and result.sent == ["email"]
    ((to, subject, text),) = world.email.sent
    assert to == "family@example.com" and subject == EMAIL_SUBJECT
    assert text.startswith(world.alert(claim).message) and "does not decide" in text
    stored = world.alert(claim)
    assert stored.delivery_status == DeliveryStatus.SENT
    assert stored.delivered_channels == ("email",) and stored.delivered_at == Clock().now()

    again = world.notify.deliver("sub_1", claim.id)
    assert again.skipped_reason == "NOT_PENDING_SENT" and len(world.email.sent) == 1


def test_sms_switched_off_is_recorded_as_not_sent_while_email_goes_out():
    world = World(sms=DisabledChannel("sms"))
    claim = update(world, sms=True, email=True)
    result = world.notify.deliver("sub_1", claim.id)
    assert result.status == DeliveryStatus.SENT and result.sent == ["email"]
    assert world.alert(claim).delivery_note == "SMS_NOT_ENABLED"


def test_sms_only_with_sms_off_fails_honestly():
    world = World(sms=DisabledChannel("sms"))
    claim = update(world, sms=True)
    result = world.notify.deliver("sub_1", claim.id)
    assert result.status == DeliveryStatus.FAILED and result.sent == []
    stored = world.alert(claim)
    assert stored.delivery_status == DeliveryStatus.FAILED
    assert stored.delivery_note == "SMS_NOT_ENABLED"


def test_a_rejected_address_is_not_retried():
    world = World(email=FakeChannel("email", [DeliveryRejected("MessageRejected")]))
    claim = update(world, email=True)
    result = world.notify.deliver("sub_1", claim.id)
    assert result.status == DeliveryStatus.FAILED and result.note == "EMAIL_REJECTED"
    assert world.sleeps == []


def test_provider_outages_are_retried_then_marked_failed():
    outage = [DeliveryUnavailable("Throttling")] * ATTEMPTS
    world = World(email=FakeChannel("email", outage))
    claim = update(world, email=True)
    result = world.notify.deliver("sub_1", claim.id)
    assert result.status == DeliveryStatus.FAILED and result.note == "EMAIL_UNAVAILABLE"
    assert len(world.sleeps) == ATTEMPTS - 1


def test_a_brief_outage_recovers_on_retry():
    world = World(email=FakeChannel("email", [DeliveryUnavailable("Throttling")]))
    claim = update(world, email=True)
    assert world.notify.deliver("sub_1", claim.id).status == DeliveryStatus.SENT
    assert len(world.email.sent) == 1


def test_in_app_only_followers_are_never_sent_anything():
    world = World()
    claim = update(world)
    assert world.alert(claim).delivery_status == DeliveryStatus.NOT_REQUIRED
    assert world.notify.deliver("sub_1", claim.id).skipped_reason == "NOT_PENDING_NOT_REQUIRED"
    assert world.email.sent == [] and world.sms.sent == []


def test_an_unfollowed_person_gets_nothing():
    world = World()
    claim = update(world, email=True)
    world.repo.subscriptions["sub_1"] = world.repo.subscriptions["sub_1"].model_copy(
        update={"active": False}
    )
    assert world.notify.deliver("sub_1", claim.id).skipped_reason == "NO_ACTIVE_CHANNEL"
    assert world.alert(claim).delivery_status == DeliveryStatus.NOT_REQUIRED
    assert world.email.sent == []


def test_a_second_delivery_that_loses_the_claim_sends_nothing():
    world = World()
    claim = update(world, email=True)
    # Another delivery of the same event took the alert first.
    world.repo.transition_alert("sub_1", claim.id, DeliveryStatus.PENDING, DeliveryStatus.SENDING)
    assert world.notify.deliver("sub_1", claim.id).skipped_reason == "NOT_PENDING_SENDING"
    assert world.email.sent == []


def test_missing_alerts_are_skipped():
    assert World().notify.deliver("sub_x", "clm_x").skipped_reason == "ALERT_NOT_FOUND"


def test_a_deceased_alert_waits_for_the_reviewer_then_goes_out():
    world = World()
    world.report("MISSING")
    world.follow(email=True)
    deceased = world.report("DECEASED", org=HOSPITAL, at="2026-10-03T07:40:00+05:30")
    alert = world.alert(deceased)
    assert alert.delivery_status == DeliveryStatus.HELD
    assert world.notify.deliver("sub_1", deceased.id).skipped_reason == "NOT_PENDING_HELD"

    # Released alerts but an item not closed yet: refuse and let the event be retried.
    world.repo.release_held_alert("sub_1", deceased.id, DeliveryStatus.PENDING)
    with pytest.raises(HeldNotReleased):
        world.notify.deliver("sub_1", deceased.id)
    assert world.email.sent == []

    review = ReviewService(world.repo, CursorCodec(b"k" * 32), clock=Clock())
    review.resolve(
        REVIEWER,
        "inc_1",
        review_item_id(ReviewItemType.HELD_ALERT, deceased.id),
        {"note": "Family told by phone."},
    )
    assert world.notify.deliver("sub_1", deceased.id).status == DeliveryStatus.SENT
    ((_, _, text),) = world.email.sent
    assert "coordinator will contact you" in text


def test_channels_report_why_they_did_not_send():
    with pytest.raises(ChannelDisabled):
        DisabledChannel("sms").send("+919876543210", "s", "t")
