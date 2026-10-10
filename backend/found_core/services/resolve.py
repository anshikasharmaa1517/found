"""Proposes possible same-person pairs and records reviewers' decisions (design 6.3, 9.7).

The resolver runs on each new person record. It reads candidates from the name token
index, scores each pair in pure code and stores a proposal with its reasons. Records are
never merged: a decision links two records and leaves both timelines as they are.

Proposals and review items are put-if-absent under keys derived from the pair, so a
repeated event or two people created at once still give one proposal per pair. A
decision is written only if the stored version is the one the reviewer saw.
"""

from dataclasses import dataclass, field
from typing import Any

from found_core.domain.auth import ADMIN, REVIEWER, Caller
from found_core.domain.enums import IdentityVerdict, ReviewItemType, SubjectType
from found_core.domain.errors import (
    BadRequest,
    Forbidden,
    NotFound,
    ValidationFailed,
    VersionConflict,
)
from found_core.domain.identity import CANDIDATE_CAP, NameParts, parse_pair_key, score
from found_core.domain.ids import review_item_id
from found_core.domain.models import IdentityDecision, IdentityProposal, ReviewItem, Subject
from found_core.domain.rules import REVIEW_PRIORITY
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository

RESOLVER = "resolver"
NOTE_MAX = 500
EVIDENCE_MAX = 20
DECISION_FIELDS = {"decision", "note", "expected_version", "evidence_claim_ids"}


@dataclass(frozen=True)
class ResolveResult:
    person_id: str
    candidates: int = 0
    proposals_created: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


class ResolveService:
    def __init__(self, repo: FoundRepository, clock: Clock | None = None) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()

    def on_person_created(self, person_id: str) -> ResolveResult:
        person = self._repo.get_subject(person_id)
        if person is None:
            # Only a demo reset removes people; the event outlived its record.
            return ResolveResult(person_id, skipped_reason="SUBJECT_NOT_FOUND")
        if person.subject_type != SubjectType.PERSON:
            return ResolveResult(person_id, skipped_reason="NOT_A_PERSON")

        candidates = self._candidates(person)
        own_places = self._places(person.id)
        created: list[str] = []
        for other in candidates:
            shared = bool(own_places) and bool(own_places & self._places(other.id))
            pair = score(person, other, shared_location=shared)
            if not pair.propose:
                continue
            # A pair a reviewer already decided is never proposed again.
            if self._repo.get_identity_decision(person.incident_id, pair.pair_key):
                continue
            proposal = IdentityProposal(
                pair_key=pair.pair_key,
                incident_id=person.incident_id,
                person_a_id=pair.person_a_id,
                person_b_id=pair.person_b_id,
                reasons=pair.reasons,
                score=pair.score,
                proposed_by=RESOLVER,
                created_at=self._clock.now(),
            )
            if self._repo.put_identity_proposal_if_absent(proposal):
                created.append(pair.pair_key)
            # Opened even when the proposal existed, so a retry after a crash completes it.
            self._open_review(proposal, person.id)
        return ResolveResult(person_id, candidates=len(candidates), proposals_created=created)

    def _candidates(self, person: Subject) -> list[Subject]:
        """Other people sharing the given name or surname token, at most CANDIDATE_CAP."""
        parts = NameParts.of(person.name_norm)
        tokens = person.tokens()
        queried = [t for t in (parts.given, parts.surname) if t in tokens] or tokens
        ids: set[str] = set()
        for token in queried:
            ids.update(self._repo.find_subject_ids_by_token(person.incident_id, token))
        ids.discard(person.id)
        found = [
            s
            for s in self._repo.get_subjects(sorted(ids))
            if s.incident_id == person.incident_id and s.subject_type == SubjectType.PERSON
        ]
        return sorted(found, key=lambda s: s.id)[:CANDIDATE_CAP]

    def _places(self, person_id: str) -> set[str]:
        return {c.location_id for c in self._repo.list_subject_claims(person_id) if c.location_id}

    def _open_review(self, proposal: IdentityProposal, person_id: str) -> None:
        item_type = ReviewItemType.IDENTITY
        self._repo.put_review_item_if_absent(
            ReviewItem(
                id=review_item_id(item_type, proposal.pair_key),
                incident_id=proposal.incident_id,
                item_type=item_type,
                ref_id=proposal.pair_key,
                subject_id=person_id,
                priority=REVIEW_PRIORITY[item_type],
                created_at=self._clock.now(),
            )
        )

    def decide(self, caller: Caller, pair_key: str, body: dict[str, Any]) -> IdentityDecision:
        """Confirm or reject a proposal with a note. Earlier decisions move to history."""
        if not (caller.has(REVIEWER) or caller.has(ADMIN)):
            raise Forbidden("Only reviewers can decide identity proposals.")
        verdict, note, expected, evidence = _decision_body(body)
        a_id, b_id = parse_pair_key(pair_key)
        people = {s.id: s for s in self._repo.get_subjects([a_id, b_id])}
        a, b = people.get(a_id), people.get(b_id)
        if (
            a is None
            or b is None
            or a.incident_id != b.incident_id
            or {a.subject_type, b.subject_type} != {SubjectType.PERSON}
        ):
            raise NotFound("Identity proposal not found.", pair_key=pair_key)
        incident_id = a.incident_id
        if self._repo.get_identity_proposal(incident_id, pair_key) is None:
            raise NotFound("Identity proposal not found.", pair_key=pair_key)
        self._check_evidence(evidence, {a_id, b_id})

        current = self._repo.get_identity_decision(incident_id, pair_key)
        current_version = current.version if current else 0
        if expected != current_version:
            raise VersionConflict(
                "This pair was decided meanwhile; reload it.", version=current_version
            )
        decision = IdentityDecision(
            pair_key=pair_key,
            incident_id=incident_id,
            person_a_id=a_id,
            person_b_id=b_id,
            decision=verdict,
            reviewer_id=caller.user_id,
            note=note,
            evidence_claim_ids=evidence,
            version=current_version + 1,
            decided_at=self._clock.now(),
            history=(*current.history, current.record()) if current else (),
        )
        if not self._repo.save_identity_decision(decision, current_version):
            raise VersionConflict("This pair was decided meanwhile; reload it.")
        self._repo.resolve_review_item(
            incident_id,
            review_item_id(ReviewItemType.IDENTITY, pair_key),
            caller.user_id,
            note,
            decision.decided_at,
        )
        return decision

    def _check_evidence(self, evidence: tuple[str, ...], pair: set[str]) -> None:
        for claim_id in evidence:
            claim = self._repo.get_claim(claim_id)
            if claim is None or claim.subject_id not in pair:
                raise ValidationFailed(
                    "Evidence must be reports about one of the two people.", claim_id=claim_id
                )


def _decision_body(body: dict[str, Any]) -> tuple[IdentityVerdict, str, int, tuple[str, ...]]:
    if set(body) - DECISION_FIELDS:
        raise BadRequest("The body may only hold " + ", ".join(sorted(DECISION_FIELDS)) + ".")
    try:
        verdict = IdentityVerdict(body.get("decision"))
    except ValueError:
        raise BadRequest("decision is required: CONFIRMED or REJECTED.") from None
    note = body.get("note")
    if not isinstance(note, str) or not note.strip() or len(note.strip()) > NOTE_MAX:
        raise BadRequest(f"note is required, at most {NOTE_MAX} characters.")
    expected = body.get("expected_version")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise BadRequest("expected_version is required: the version you saw, 0 if undecided.")
    evidence = body.get("evidence_claim_ids", [])
    if (
        not isinstance(evidence, list)
        or len(evidence) > EVIDENCE_MAX
        or not all(isinstance(e, str) and e for e in evidence)
    ):
        raise BadRequest(f"evidence_claim_ids must be a list of at most {EVIDENCE_MAX} ids.")
    return verdict, note.strip(), expected, tuple(dict.fromkeys(evidence))
