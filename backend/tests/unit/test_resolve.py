from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import IdentityVerdict, ReviewItemType, ReviewStatus
from found_core.domain.errors import (
    BadRequest,
    Forbidden,
    NotFound,
    ValidationFailed,
    VersionConflict,
)
from found_core.domain.identity import CANDIDATE_CAP, pair_key
from found_core.domain.ids import review_item_id
from found_core.services.ingest import IngestService
from found_core.services.people import PeopleService
from found_core.services.resolve import ResolveService
from found_core.services.review import ReviewService

REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
REVIEWER_2 = Caller(user_id="rev_2", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}
BRIDGE = {"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354}
SCHOOL = {"name": "Upper School", "lat": 30.7301, "lon": 78.4402}


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
        self.resolver = ResolveService(self.repo, clock=self.clock)
        self.refs = 0

    def person(self, name, age=None, place=None, org=POLICE, resolve=True):
        """Publish a report about a new person record and run the resolver on it."""
        self.refs += 1
        new = {"name": name, **({"age": age} if age is not None else {})}
        claim = self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": {"type": "PERSON", "new": new},
                    "claim_type": "MISSING",
                    "original_text": f"{name} reported missing.",
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": "2026-10-02T21:10:00+05:30",
                    **({"location": place} if place else {}),
                }
            )
        ).claim
        if resolve:
            self.last = self.resolver.on_person_created(claim.subject_id)
        return claim

    def decide(self, key, verdict="CONFIRMED", version=0, caller=REVIEWER, **extra):
        body = {"decision": verdict, "note": "Same age, same bridge.", "expected_version": version}
        return self.resolver.decide(caller, key, {**body, **extra})


@pytest.fixture
def world():
    return World()


def test_a_likely_duplicate_is_proposed_with_reasons_and_queued(world):
    first = world.person("Maya Rawat", 24, BRIDGE)
    second = world.person("Maya R.", 24, BRIDGE, org=NGO)
    key = pair_key(first.subject_id, second.subject_id)
    assert world.last.proposals_created == [key] and world.last.candidates == 1

    proposal = world.repo.get_identity_proposal("inc_1", key)
    assert proposal.reasons == ("GIVEN_EXACT", "AGE_EQUAL", "SHARED_LOCATION")
    assert proposal.score == 55 and proposal.proposed_by == "resolver"
    item = world.repo.get_review_item("inc_1", review_item_id(ReviewItemType.IDENTITY, key))
    assert item.ref_id == key and item.priority == 3 and item.subject_id == second.subject_id


def test_names_alone_never_propose(world):
    world.person("Maya Rawat")
    world.person("Maya Rawat", org=NGO)
    assert world.last.candidates == 1 and world.last.proposals_created == []
    assert world.repo.identity_proposals == {} and world.repo.review_items == {}


def test_places_only_count_when_they_are_the_same_place(world):
    world.person("Maya R.", 24, BRIDGE)
    world.person("Maya Rawat", 30, SCHOOL, org=NGO)
    assert world.last.proposals_created == []


def test_a_repeated_event_creates_nothing_new(world):
    world.person("Maya Rawat", 24, BRIDGE)
    second = world.person("Maya Rawat", 24, BRIDGE, org=NGO)
    again = world.resolver.on_person_created(second.subject_id)
    assert again.proposals_created == [] and len(world.repo.identity_proposals) == 1
    assert len(world.repo.review_items) == 1


def test_the_earlier_record_finds_the_later_one_without_a_second_proposal(world):
    first = world.person("Maya Rawat", 24, BRIDGE)
    world.person("Maya Rawat", 24, BRIDGE, org=NGO)
    assert world.resolver.on_person_created(first.subject_id).proposals_created == []
    assert len(world.repo.identity_proposals) == 1


def test_missing_records_and_other_subjects_are_skipped(world):
    assert world.resolver.on_person_created("per_gone").skipped_reason == "SUBJECT_NOT_FOUND"


def test_candidates_are_capped(world):
    for _ in range(CANDIDATE_CAP + 3):
        world.person("Maya Rawat", 24, resolve=False)
    world.person("Maya Rawat", 24)
    assert world.last.candidates == CANDIDATE_CAP
    assert len(world.last.proposals_created) == CANDIDATE_CAP


def proposed(world):
    first = world.person("Maya Rawat", 24, BRIDGE)
    second = world.person("Maya Rawat", 24, BRIDGE, org=NGO)
    return first, second, pair_key(first.subject_id, second.subject_id)


def test_a_reviewer_confirms_and_the_records_stay_separate(world):
    first, second, key = proposed(world)
    decision = world.decide(key, evidence_claim_ids=[first.id, second.id])
    assert decision.decision == IdentityVerdict.CONFIRMED and decision.version == 1
    assert decision.reviewer_id == "rev_1" and decision.history == ()
    assert decision.evidence_claim_ids == (first.id, second.id)
    # Nothing is merged: both people and their claims are untouched.
    assert world.repo.get_subject(first.subject_id) and world.repo.get_subject(second.subject_id)
    assert [c.id for c in world.repo.list_subject_claims(second.subject_id)] == [second.id]
    item = world.repo.get_review_item("inc_1", review_item_id(ReviewItemType.IDENTITY, key))
    assert item.status == ReviewStatus.DONE and item.resolved_by == "rev_1"


def test_changing_a_decision_keeps_the_earlier_one(world):
    _, _, key = proposed(world)
    world.decide(key)
    world.clock.at += timedelta(hours=1)
    changed = world.decide(key, "REJECTED", version=1, caller=REVIEWER_2)
    assert changed.version == 2 and changed.reviewer_id == "rev_2"
    (earlier,) = changed.history
    assert earlier.decision == IdentityVerdict.CONFIRMED and earlier.reviewer_id == "rev_1"
    assert earlier.version == 1 and earlier.decided_at < changed.decided_at
    third = world.decide(key, version=2)
    assert [h.version for h in third.history] == [1, 2]


def test_a_stale_version_is_a_conflict(world):
    _, _, key = proposed(world)
    world.decide(key)
    with pytest.raises(VersionConflict):
        world.decide(key, "REJECTED", version=0, caller=REVIEWER_2)
    assert world.repo.get_identity_decision("inc_1", key).decision == IdentityVerdict.CONFIRMED


def test_a_decided_pair_is_not_proposed_again(world):
    _, second, key = proposed(world)
    world.decide(key, "REJECTED")
    world.repo.identity_proposals.clear()
    assert world.resolver.on_person_created(second.subject_id).proposals_created == []


def test_only_reviewers_decide(world):
    _, _, key = proposed(world)
    with pytest.raises(Forbidden):
        world.decide(key, caller=FAMILY)


def test_evidence_must_be_about_the_pair(world):
    _, _, key = proposed(world)
    other = world.person("Arjun Negi", 31)
    with pytest.raises(ValidationFailed):
        world.decide(key, evidence_claim_ids=[other.id])
    with pytest.raises(ValidationFailed):
        world.decide(key, evidence_claim_ids=["clm_missing"])


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "MERGE", "note": "x", "expected_version": 0},
        {"decision": "CONFIRMED", "note": " ", "expected_version": 0},
        {"decision": "CONFIRMED", "note": "x"},
        {"decision": "CONFIRMED", "note": "x", "expected_version": True},
        {"decision": "CONFIRMED", "note": "x", "expected_version": 0, "merge": True},
        {"decision": "CONFIRMED", "note": "x", "expected_version": 0, "evidence_claim_ids": "c"},
    ],
)
def test_bad_bodies_are_refused(world, body):
    _, _, key = proposed(world)
    with pytest.raises(BadRequest):
        world.resolver.decide(REVIEWER, key, body)


def test_unknown_pairs_are_not_found(world):
    first, _, _ = proposed(world)
    lone = world.person("Arjun Negi", 31)
    with pytest.raises(NotFound):
        world.decide(pair_key(first.subject_id, lone.subject_id))
    with pytest.raises(NotFound):
        world.decide("per_0|per_1")


def test_the_person_page_shows_the_decision_and_the_queue_shows_the_pair(world):
    first, second, key = proposed(world)
    queue = ReviewService(world.repo, CursorCodec(b"k" * 32), clock=world.clock)
    (entry,) = queue.queue(REVIEWER, "inc_1").entries
    assert entry.proposal.pair_key == key
    assert [p.id for p in entry.people] == sorted([first.subject_id, second.subject_id])
    with pytest.raises(BadRequest):
        queue.resolve(REVIEWER, "inc_1", entry.item.id, {})

    world.decide(key)
    people = PeopleService(world.repo, CursorCodec(b"k" * 32))
    for pid in (first.subject_id, second.subject_id):
        (decision,) = people.profile(FAMILY, pid).identity
        assert decision.pair_key == key
    assert people.profile(FAMILY, world.person("Arjun Negi", 31).subject_id).identity == ()


def test_subjects_that_are_not_people_are_skipped(world):
    from found_core.domain.models import Subject

    world.repo.subjects["plc_1"] = Subject(
        id="plc_1",
        incident_id="inc_1",
        subject_type="PLACE",
        display_name="Old Bridge",
        name_norm="old bridge",
    )
    assert world.resolver.on_person_created("plc_1").skipped_reason == "NOT_A_PERSON"


def test_demo_reset_clears_proposals_and_decisions(world):
    _, _, key = proposed(world)
    world.decide(key)
    world.repo.delete_incident_data("inc_1")
    assert world.repo.identity_proposals == {} and world.repo.identity_decisions == {}
