from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryBudgetLedger, InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import DeliveryStatus, ReviewItemType, ReviewStatus
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.errors import BadRequest, Forbidden, NotFound, VersionConflict
from found_core.domain.ids import review_item_id
from found_core.domain.investigation import InvestigationConfig
from found_core.domain.models import ReviewItem, Settings, Subscription
from found_core.services.ingest import IngestService
from found_core.services.investigations import InvestigationService
from found_core.services.people import PeopleService
from found_core.services.review import ReviewService
from found_core.services.watch import WatchService
from found_core.tools.service import AgentToolService

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}
LATER = "2026-10-03T07:40:00+05:30"


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

    def now(self):
        return self.at


class Queue:
    def send(self, investigation_id):
        pass


class World:
    def __init__(self):
        self.clock = Clock()
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.settings = Settings(live_enabled=True)
        self.ingest = IngestService(self.repo, clock=self.clock, sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=self.clock)
        self.codec = CursorCodec(b"k" * 32)
        self.review = ReviewService(self.repo, self.codec, clock=self.clock)
        self.refs = 0
        self.person = None

    def report(self, claim_type, reported_at="2026-10-02T21:10:00+05:30", org=POLICE, text=None):
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
                    "original_text": text or f"Report {self.refs} about Maya Rawat.",
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": reported_at,
                }
            )
        ).claim
        self.person = claim.subject_id
        self.watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
        return claim

    def follow(self, sub_id, sms=False):
        self.repo.add_subscription(
            Subscription(
                id=sub_id,
                subject_id=self.person,
                user_id=f"user_{sub_id}",
                channel_sms=sms,
                phone_e164="+919876543210" if sms else None,
            )
        )


@pytest.fixture
def world():
    return World()


def test_queue_lists_open_items_most_urgent_first_with_context(world):
    world.report("MISSING")
    world.clock.at += timedelta(minutes=1)
    world.report("FOUND_SAFE", reported_at=None, org=HOSPITAL)  # conflict, priority 2
    world.clock.at += timedelta(minutes=1)
    deceased = world.report("DECEASED", reported_at=LATER, org=HOSPITAL)  # held alert, priority 1
    page = world.review.queue(REVIEWER, "inc_1")
    assert [e.item.item_type for e in page.entries] == [
        ReviewItemType.HELD_ALERT,
        ReviewItemType.CONFLICT,
    ]
    held = page.entries[0]
    assert held.claim.id == deceased.id and held.subject.display_name == "Maya Rawat"
    assert held.source.name == "Central Hospital Demo"
    only = world.review.queue(REVIEWER, "inc_1", item_type="conflict")
    assert [e.item.item_type for e in only.entries] == [ReviewItemType.CONFLICT]
    assert page.next_cursor is None


def test_queue_pages_with_a_signed_cursor(world):
    for n in range(3):
        world.repo.put_review_item_if_absent(
            ReviewItem(
                id=f"rev_{n}",
                incident_id="inc_1",
                item_type="conflict",
                ref_id=f"clm_{n}",
                priority=2,
                created_at=world.clock.at + timedelta(minutes=n),
            )
        )
    first = world.review.queue(REVIEWER, "inc_1", limit="2")
    assert [e.item.id for e in first.entries] == ["rev_0", "rev_1"]
    second = world.review.queue(REVIEWER, "inc_1", limit="2", cursor=first.next_cursor)
    assert [e.item.id for e in second.entries] == ["rev_2"] and second.next_cursor is None
    with pytest.raises(BadRequest):
        world.review.queue(REVIEWER, "inc_1", item_type="identity", cursor=first.next_cursor)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"item_type": "gossip"}, BadRequest),
        ({"status": "CLOSED"}, BadRequest),
        ({"limit": "500"}, BadRequest),
    ],
)
def test_queue_validates_filters(world, kwargs, error):
    with pytest.raises(error):
        world.review.queue(REVIEWER, "inc_1", **kwargs)


def test_queue_is_for_reviewers_of_known_incidents(world):
    with pytest.raises(Forbidden):
        world.review.queue(FAMILY, "inc_1")
    with pytest.raises(NotFound):
        world.review.queue(REVIEWER, "inc_x")


def test_release_frees_every_held_alert_and_shows_the_claim(world):
    world.report("MISSING")
    world.follow("sub_a", sms=True)
    world.follow("sub_b")
    deceased = world.report("DECEASED", reported_at=LATER, org=HOSPITAL)
    held = [a for a in world.repo.alerts.values() if a.claim_id == deceased.id]
    assert {a.delivery_status for a in held} == {DeliveryStatus.HELD}
    people = PeopleService(world.repo, world.codec)
    assert deceased.id in people.profile(FAMILY, world.person).withheld

    rid = review_item_id(ReviewItemType.HELD_ALERT, deceased.id)
    result = world.review.resolve(REVIEWER, "inc_1", rid, {"note": "Family informed by phone."})
    assert result.alerts_released == 2
    assert result.item.status == ReviewStatus.DONE and result.item.resolved_by == "rev_1"
    assert result.item.note == "Family informed by phone."
    status = {
        a.subscription_id: a.delivery_status
        for a in world.repo.alerts.values()
        if a.claim_id == deceased.id
    }
    assert status == {"sub_a": DeliveryStatus.PENDING, "sub_b": DeliveryStatus.NOT_REQUIRED}
    assert people.profile(FAMILY, world.person).withheld == frozenset()
    assert world.review.queue(REVIEWER, "inc_1").entries == []
    done = world.review.queue(REVIEWER, "inc_1", status="DONE")
    assert [e.item.id for e in done.entries] == [rid]


def test_release_without_followers_still_shows_the_claim(world):
    deceased = world.report("DECEASED", reported_at=LATER, org=HOSPITAL)
    rid = review_item_id(ReviewItemType.HELD_ALERT, deceased.id)
    assert world.review.resolve(REVIEWER, "inc_1", rid, {}).alerts_released == 0
    people = PeopleService(world.repo, world.codec)
    assert people.profile(FAMILY, world.person).withheld == frozenset()


def test_second_decision_on_one_item_is_a_conflict(world):
    deceased = world.report("DECEASED", reported_at=LATER, org=HOSPITAL)
    rid = review_item_id(ReviewItemType.HELD_ALERT, deceased.id)
    world.review.resolve(REVIEWER, "inc_1", rid, {})
    with pytest.raises(VersionConflict):
        world.review.resolve(REVIEWER, "inc_1", rid, {})


@pytest.mark.parametrize("body", [{"note": 5}, {"note": "x" * 501}, {"decision": "x"}])
def test_resolve_checks_the_body(world, body):
    deceased = world.report("DECEASED", reported_at=LATER, org=HOSPITAL)
    rid = review_item_id(ReviewItemType.HELD_ALERT, deceased.id)
    with pytest.raises(BadRequest):
        world.review.resolve(REVIEWER, "inc_1", rid, body)


def test_resolve_needs_a_reviewer_and_a_known_item(world):
    with pytest.raises(Forbidden):
        world.review.resolve(FAMILY, "inc_1", "rev_x", {})
    with pytest.raises(NotFound):
        world.review.resolve(REVIEWER, "inc_1", "rev_x", {})


def finished_finding(world):
    source = world.report("FOUND_SAFE", org=HOSPITAL, text="Maya Rawat admitted to ward 3.")
    relay = world.report(
        "FOUND_SAFE", org=NGO, text="According to Central Hospital Demo, Maya Rawat was admitted."
    )
    config = InvestigationConfig(model_id="model-a")
    starter = InvestigationService(world.repo, InMemoryBudgetLedger(), Queue(), config, world.clock)
    inv = starter.start(REVIEWER, relay.id).investigation
    world.repo.update_investigation_if(inv.id, S.QUEUED, {"status": S.RUNNING})
    tools = AgentToolService(world.repo, config, clock=world.clock)
    result = tools.call(
        "record_finding",
        {
            "investigation_id": inv.id,
            "attribution": "RELAY",
            "referenced_source_id": source.source_id,
            "comparison": "SUPPORTS",
            "summary": "Repeats the hospital report.",
            "citations": [
                {"claim_id": relay.id, "excerpt": "According to Central Hospital Demo"},
                {"claim_id": source.id, "excerpt": "admitted to ward 3"},
            ],
        },
    )
    assert result["ok"], result
    return inv.id


def test_finding_review_records_the_verdict_and_closes_its_item(world):
    inv_id = finished_finding(world)
    page = world.review.queue(REVIEWER, "inc_1", item_type="finding")
    (entry,) = page.entries
    assert entry.investigation.id == inv_id and entry.claim is not None
    with pytest.raises(BadRequest):
        world.review.resolve(REVIEWER, "inc_1", entry.item.id, {})

    reviewed = world.review.review_finding(
        REVIEWER, inv_id, {"decision": "ACCEPTED", "note": "Matches the ward record."}
    )
    assert reviewed.review_status == "ACCEPTED" and reviewed.reviewed_by == "rev_1"
    assert reviewed.status == S.NEEDS_REVIEW
    assert world.review.queue(REVIEWER, "inc_1", item_type="finding").entries == []
    with pytest.raises(VersionConflict):
        world.review.review_finding(REVIEWER, inv_id, {"decision": "DISPUTED"})


@pytest.mark.parametrize("body", [{}, {"decision": "MAYBE"}, {"decision": "ACCEPTED", "x": 1}])
def test_finding_review_checks_the_body(world, body):
    inv_id = finished_finding(world)
    with pytest.raises(BadRequest):
        world.review.review_finding(REVIEWER, inv_id, body)


def test_only_a_recorded_finding_can_be_reviewed(world):
    relay = world.report("FOUND_SAFE", org=NGO)
    config = InvestigationConfig(model_id="model-a")
    starter = InvestigationService(world.repo, InMemoryBudgetLedger(), Queue(), config, world.clock)
    inv = starter.start(REVIEWER, relay.id).investigation
    with pytest.raises(BadRequest):
        world.review.review_finding(REVIEWER, inv.id, {"decision": "ACCEPTED"})
    with pytest.raises(NotFound):
        world.review.review_finding(REVIEWER, "inv_x", {"decision": "ACCEPTED"})
    with pytest.raises(Forbidden):
        world.review.review_finding(FAMILY, inv.id, {"decision": "ACCEPTED"})
