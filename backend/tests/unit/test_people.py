from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import Relation
from found_core.domain.errors import BadRequest, Forbidden, NotFound
from found_core.domain.models import Organization
from found_core.services.ingest import IngestService
from found_core.services.people import PeopleService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}

REVIEWER = Caller(user_id="rev", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam", groups=frozenset({"family"}))
PUBLISHER = Caller(user_id="pub", groups=frozenset({"publisher"}), org_id="org_h")
OTHER_PUBLISHER = Caller(user_id="pub2", groups=frozenset({"publisher"}), org_id="org_x")

PEOPLE = [("Maya Rawat", 24), ("Mohan Rawat", 60), ("Asha Devi", None), ("Ravi Kumar", 30)]


class World:
    def __init__(self) -> None:
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.add_incident("inc_2")
        self.repo.add_organization(
            Organization(
                id="org_h",
                incident_id="inc_1",
                name="Central Hospital Demo",
                name_norm="central hospital demo",
                org_type="HOSPITAL",
            )
        )
        self.ingest = IngestService(self.repo, clock=FixedClock(), sleep=lambda _: None)
        self.service = PeopleService(self.repo, CursorCodec(b"k" * 32))
        self.refs = 0

    def publish(self, subject, org=POLICE, incident="inc_1", **overrides):
        self.refs += 1
        data = {
            "incident_id": incident,
            **org,
            "actor": "user_1",
            "subject": subject,
            "claim_type": "MISSING",
            "original_text": "Reported missing near the old bridge.",
            "external_reference": f"REF-{self.refs}",
            "reported_at": "2026-10-02T21:10:00+05:30",
            **overrides,
        }
        return self.ingest.publish(PublishCommand.parse(data)).claim

    def person(self, name, age=None, incident="inc_1"):
        new = {"name": name, **({"age": age} if age is not None else {})}
        return self.publish({"type": "PERSON", "new": new}, incident=incident).subject_id


@pytest.fixture
def world():
    w = World()
    w.ids = {name: w.person(name, age) for name, age in PEOPLE}
    w.person("Maya Sharma", 24, incident="inc_2")
    return w


def names(page):
    return [p.display_name for p in page.people]


def test_list_is_sorted_by_name_and_scoped_to_incident(world):
    page = world.service.list_people(REVIEWER, "inc_1")
    assert names(page) == ["Asha Devi", "Maya Rawat", "Mohan Rawat", "Ravi Kumar"]
    assert page.next_cursor is None


def test_list_pages_with_cursor(world):
    first = world.service.list_people(REVIEWER, "inc_1", limit="3")
    assert names(first) == ["Asha Devi", "Maya Rawat", "Mohan Rawat"]
    second = world.service.list_people(REVIEWER, "inc_1", limit="3", cursor=first.next_cursor)
    assert names(second) == ["Ravi Kumar"] and second.next_cursor is None


def test_exact_page_size_has_no_next_cursor(world):
    page = world.service.list_people(REVIEWER, "inc_1", limit="4")
    assert len(page.people) == 4 and page.next_cursor is None


def test_age_filter_keeps_near_ages_and_unknown(world):
    page = world.service.list_people(REVIEWER, "inc_1", age="26")
    assert names(page) == ["Asha Devi", "Maya Rawat"]


def test_age_filter_pages_past_filtered_people(world):
    first = world.service.list_people(REVIEWER, "inc_1", age="60", limit="1")
    assert names(first) == ["Asha Devi"]
    second = world.service.list_people(
        REVIEWER, "inc_1", age="60", limit="1", cursor=first.next_cursor
    )
    assert names(second) == ["Mohan Rawat"] and second.next_cursor is None


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("rawat", ["Maya Rawat", "Mohan Rawat"]),
        ("RAW", ["Maya Rawat", "Mohan Rawat"]),
        ("ma ra", ["Maya Rawat"]),
        ("rawat maya", ["Maya Rawat"]),
        ("kumar", ["Ravi Kumar"]),
        ("zed", []),
    ],
)
def test_search_matches_every_token_by_prefix(world, q, expected):
    assert names(world.service.list_people(REVIEWER, "inc_1", q=q)) == expected


def test_search_never_crosses_incidents(world):
    assert names(world.service.list_people(REVIEWER, "inc_2", q="maya")) == ["Maya Sharma"]


def test_search_with_age_and_paging(world):
    first = world.service.list_people(REVIEWER, "inc_1", q="rawat", limit="1")
    assert names(first) == ["Maya Rawat"]
    second = world.service.list_people(
        REVIEWER, "inc_1", q="rawat", limit="1", cursor=first.next_cursor
    )
    assert names(second) == ["Mohan Rawat"] and second.next_cursor is None
    aged = world.service.list_people(REVIEWER, "inc_1", q="rawat", age="59")
    assert names(aged) == ["Mohan Rawat"]


def test_cursor_from_another_listing_is_rejected(world):
    first = world.service.list_people(REVIEWER, "inc_1", limit="1")
    with pytest.raises(BadRequest):
        world.service.list_people(REVIEWER, "inc_1", q="rawat", limit="1", cursor=first.next_cursor)


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": "0"}, {"limit": "101"}, {"limit": "ten"}, {"age": "-1"}, {"age": "x"}, {"q": "a"}],
)
def test_bad_query_parameters(world, kwargs):
    with pytest.raises(BadRequest):
        world.service.list_people(REVIEWER, "inc_1", **kwargs)


def test_unknown_incident_is_not_found(world):
    with pytest.raises(NotFound):
        world.service.list_people(REVIEWER, "inc_missing")


def test_publisher_reads_only_their_incidents(world):
    assert names(world.service.list_people(PUBLISHER, "inc_1"))
    with pytest.raises(Forbidden):
        world.service.list_people(PUBLISHER, "inc_2")
    with pytest.raises(Forbidden):
        world.service.list_people(OTHER_PUBLISHER, "inc_1")


def test_caller_without_a_role_is_forbidden(world):
    with pytest.raises(Forbidden):
        world.service.list_people(Caller(user_id="u", groups=frozenset()), "inc_1")


@pytest.fixture
def maya(world):
    pid = world.ids["Maya Rawat"]
    subject = {"type": "PERSON", "id": pid}
    world.publish(
        subject,
        org=HOSPITAL,
        claim_type="FOUND_SAFE",
        original_text="Maya Rawat, 24, admitted to Central Hospital Demo ward 3, stable.",
        reported_at="2026-10-03T07:40:00+05:30",
    )
    world.publish(
        subject,
        claim_type="SEEN_AT_LOCATION",
        original_text="Seen at the relief camp.",
        reported_at="2026-10-02T23:00:00+05:30",
    )
    world.publish(
        subject,
        claim_type="MISSING",
        original_text="Earlier police note.",
        reported_at="2026-10-02T18:00:00+05:30",
    )
    return pid


def test_profile_cites_latest_report_and_names_conflicting_source(world, maya):
    profile = world.service.profile(FAMILY, maya)
    assert profile.person.display_name == "Maya Rawat"
    assert profile.claim_count == 4
    assert profile.summary.label == "Reported found safe"
    assert profile.summary.basis == "Latest dated status report"
    cited = world.repo.get_claim(profile.summary.cited_claim_id)
    assert cited.claim_type == "FOUND_SAFE"
    assert [c.claim_type for c in profile.conflicts] == ["MISSING"]
    assert profile.sources[profile.conflicts[0].source_id].name == "District Police Demo"


def test_timeline_is_ordered_by_reported_time_with_relations(world, maya):
    timeline = world.service.timeline(FAMILY, maya)
    got = [(e.claim.seq, e.relation) for e in timeline.entries]
    assert got == [
        (4, Relation.HISTORICAL),
        (1, Relation.FIRST),
        (3, Relation.NOT_STATUS),
        (2, Relation.UPDATE),
    ]
    assert timeline.next_cursor is None
    assert timeline.profile.summary.cited_claim_id == timeline.entries[-1].claim.id


def test_timeline_desc_and_paging(world, maya):
    seqs = []
    cursor = None
    while True:
        page = world.service.timeline(REVIEWER, maya, order="desc", limit="3", cursor=cursor)
        seqs += [e.claim.seq for e in page.entries]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seqs == [2, 3, 1, 4]


def test_timeline_cursor_is_bound_to_person_and_order(world, maya):
    page = world.service.timeline(REVIEWER, maya, limit="1")
    with pytest.raises(BadRequest):
        world.service.timeline(REVIEWER, maya, order="desc", limit="1", cursor=page.next_cursor)
    other = world.ids["Mohan Rawat"]
    with pytest.raises(BadRequest):
        world.service.timeline(REVIEWER, other, limit="1", cursor=page.next_cursor)


def test_timeline_rejects_bad_order(world, maya):
    with pytest.raises(BadRequest):
        world.service.timeline(REVIEWER, maya, order="sideways")


def test_unknown_person_is_not_found(world):
    with pytest.raises(NotFound):
        world.service.profile(REVIEWER, "per_missing")
    with pytest.raises(NotFound):
        world.service.timeline(REVIEWER, "per_missing")


def test_publisher_cannot_read_people_of_other_incidents(world):
    pid = next(iter(s.id for s in world.repo.subjects.values() if s.incident_id == "inc_2"))
    with pytest.raises(Forbidden):
        world.service.timeline(PUBLISHER, pid)
