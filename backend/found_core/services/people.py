"""Read models for people: list and search, profile, timeline (design Sections 6.10, 7.3).

Nothing here is cached. Summaries come from the same pure rules the watcher uses, so the
page and the alerts always agree.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from found_core.domain.auth import Caller
from found_core.domain.cursor import CursorCodec, parse_limit
from found_core.domain.enums import Relation, ReviewItemType, ReviewStatus, SubjectType
from found_core.domain.errors import BadRequest, NotFound
from found_core.domain.ids import review_item_id
from found_core.domain.models import Claim, Source, Subject
from found_core.domain.normalize import name_tokens
from found_core.domain.rules import CitedSummary, age_matches, relations, report_order, summarize
from found_core.domain.visibility import is_sensitive, masked_summary, sees_sensitive, withheld_ids
from found_core.ports.repository import FoundRepository, NamePosition
from found_core.services.access import ensure_can_read

MAX_AGE = 120


@dataclass(frozen=True)
class PeoplePage:
    people: list[Subject]
    next_cursor: str | None


@dataclass(frozen=True)
class PersonProfile:
    person: Subject
    summary: CitedSummary
    conflicts: list[Claim]
    sources: dict[str, Source]
    claim_count: int
    # Claims this caller sees only as a neutral notice (product rule 8).
    withheld: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TimelineEntry:
    claim: Claim
    relation: Relation
    withheld: bool = False


@dataclass(frozen=True)
class Timeline:
    profile: PersonProfile
    entries: list[TimelineEntry]
    next_cursor: str | None


def _parse_age(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        age = int(raw)
    except ValueError:
        raise BadRequest("age must be a whole number.") from None
    if not 0 <= age <= MAX_AGE:
        raise BadRequest(f"age must be between 0 and {MAX_AGE}.")
    return age


def _parse_order(raw: str | None) -> str:
    order = raw or "asc"
    if order not in ("asc", "desc"):
        raise BadRequest("order must be asc or desc.")
    return order


def _name_key(subject: Subject) -> tuple[str, str]:
    return (subject.name_norm, subject.id)


class PeopleService:
    def __init__(self, repo: FoundRepository, cursors: CursorCodec) -> None:
        self._repo = repo
        self._cursors = cursors

    def list_people(
        self,
        caller: Caller,
        incident_id: str,
        *,
        q: str | None = None,
        age: str | None = None,
        limit: str | None = None,
        cursor: str | None = None,
    ) -> PeoplePage:
        page_size = parse_limit(limit)
        wanted_age = _parse_age(age)
        tokens = name_tokens(q or "")
        if q and q.strip() and not tokens:
            raise BadRequest("Search needs at least 2 letters.")
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)

        scope = f"people:{incident_id}:{' '.join(tokens)}:{wanted_age}"
        after = self._name_position(scope, cursor)
        if tokens:
            found = self._search(incident_id, tokens, wanted_age, after, page_size + 1)
        else:
            found = self._browse(incident_id, wanted_age, after, page_size + 1)

        people = found[:page_size]
        next_cursor = None
        if len(found) > page_size:
            last = people[-1]
            next_cursor = self._cursors.encode(scope, {"n": last.name_norm, "i": last.id})
        return PeoplePage(people=people, next_cursor=next_cursor)

    def profile(self, caller: Caller, person_id: str) -> PersonProfile:
        person, claims = self._person_with_claims(caller, person_id)
        return self._profile(person, claims, caller)

    def timeline(
        self,
        caller: Caller,
        person_id: str,
        *,
        order: str | None = None,
        limit: str | None = None,
        cursor: str | None = None,
    ) -> Timeline:
        page_size = parse_limit(limit)
        direction = _parse_order(order)
        person, claims = self._person_with_claims(caller, person_id)

        ordered = sorted(claims, key=report_order, reverse=direction == "desc")
        scope = f"timeline:{person_id}:{direction}"
        start = 0
        if cursor:
            seq = self._cursors.decode(scope, cursor).get("s")
            index = next((i for i, c in enumerate(ordered) if c.seq == seq), None)
            if index is None:
                raise BadRequest("Cursor is invalid.")
            start = index + 1

        page = ordered[start : start + page_size]
        relation_of = relations(claims)
        next_cursor = None
        if start + page_size < len(ordered):
            next_cursor = self._cursors.encode(scope, {"s": page[-1].seq})
        profile = self._profile(person, claims, caller)
        return Timeline(
            profile=profile,
            entries=[
                TimelineEntry(
                    claim=c, relation=relation_of[c.id], withheld=c.id in profile.withheld
                )
                for c in page
            ],
            next_cursor=next_cursor,
        )

    def _person_with_claims(self, caller: Caller, person_id: str) -> tuple[Subject, list[Claim]]:
        person = self._repo.get_subject(person_id)
        if person is None or person.subject_type != SubjectType.PERSON:
            raise NotFound("Person not found.", person_id=person_id)
        ensure_can_read(self._repo, caller, person.incident_id)
        return person, self._repo.list_subject_claims(person_id)

    def _profile(self, person: Subject, claims: Sequence[Claim], caller: Caller) -> PersonProfile:
        withheld = withheld_ids(claims, caller, self._released(person, claims, caller))
        summary = summarize(claims, person.subject_type)
        by_id = {c.id: c for c in claims}
        return PersonProfile(
            person=person,
            summary=masked_summary(summary, withheld),
            withheld=withheld,
            conflicts=[by_id[cid] for cid in summary.conflicts],
            sources={s.id: s for s in self._repo.list_sources(person.incident_id)},
            claim_count=len(claims),
        )

    def _released(self, person: Subject, claims: Sequence[Claim], caller: Caller) -> set[str]:
        """Sensitive claims a reviewer has released: their held-alert review item is done."""
        if sees_sensitive(caller):
            return set()
        released: set[str] = set()
        for claim in claims:
            if not is_sensitive(claim):
                continue
            item = self._repo.get_review_item(
                person.incident_id, review_item_id(ReviewItemType.HELD_ALERT, claim.id)
            )
            if item is not None and item.status == ReviewStatus.DONE:
                released.add(claim.id)
        return released

    def _name_position(self, scope: str, cursor: str | None) -> NamePosition | None:
        if not cursor:
            return None
        position = self._cursors.decode(scope, cursor)
        name, subject_id = position.get("n"), position.get("i")
        if not isinstance(name, str) or not isinstance(subject_id, str):
            raise BadRequest("Cursor is invalid.")
        return NamePosition(name_norm=name, subject_id=subject_id)

    def _browse(
        self, incident_id: str, age: int | None, after: NamePosition | None, want: int
    ) -> list[Subject]:
        found: list[Subject] = []
        while len(found) < want:
            batch = self._repo.list_subjects(incident_id, SubjectType.PERSON, want, after)
            found += [s for s in batch if age is None or age_matches(s.age, age)]
            if len(batch) < want:
                break
            after = NamePosition(name_norm=batch[-1].name_norm, subject_id=batch[-1].id)
        return found[:want]

    def _search(
        self,
        incident_id: str,
        tokens: list[str],
        age: int | None,
        after: NamePosition | None,
        want: int,
    ) -> list[Subject]:
        # The longest token is the most selective prefix to query with.
        ids = self._repo.find_subject_ids_by_token(incident_id, max(tokens, key=len))
        start = (after.name_norm, after.subject_id) if after else None
        matches = [
            s
            for s in self._repo.get_subjects(ids)
            if s.incident_id == incident_id
            and s.subject_type == SubjectType.PERSON
            and all(any(t.startswith(q) for t in s.tokens()) for q in tokens)
            and (age is None or age_matches(s.age, age))
            and (start is None or _name_key(s) > start)
        ]
        return sorted(matches, key=_name_key)[:want]
