"""The review queue and the decisions taken from it (design Sections 6.10, 7.4, 9.6).

Reviewers see open items most urgent first. Each decision is a conditional write, so a
second reviewer acting on the same item gets a conflict instead of a silent overwrite.

Releasing a held sensitive report frees every held alert for that claim (owner decision
6) before the item is closed. If the run stops between the two, repeating the release
finds the alerts already released and closes the item, so the release is never lost.
"""

from dataclasses import dataclass
from typing import Any

from found_core.domain.auth import ADMIN, REVIEWER, Caller
from found_core.domain.cursor import CursorCodec, parse_limit
from found_core.domain.enums import FindingReview, ReviewItemType, ReviewStatus
from found_core.domain.errors import BadRequest, Forbidden, NotFound, VersionConflict
from found_core.domain.ids import review_item_id
from found_core.domain.investigation import TERMINAL_STATUSES
from found_core.domain.models import (
    Claim,
    IdentityProposal,
    Investigation,
    ReviewItem,
    Source,
    Subject,
)
from found_core.domain.rules import released_delivery
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository

NOTE_MAX = 500


@dataclass(frozen=True)
class ReviewEntry:
    item: ReviewItem
    claim: Claim | None = None
    subject: Subject | None = None
    source: Source | None = None
    investigation: Investigation | None = None
    # Identity items: the proposal and both people, person_a first.
    proposal: IdentityProposal | None = None
    people: tuple[Subject, ...] = ()


@dataclass(frozen=True)
class ReviewPage:
    entries: list[ReviewEntry]
    next_cursor: str | None


@dataclass(frozen=True)
class ResolveResult:
    item: ReviewItem
    alerts_released: int = 0


def _require_reviewer(caller: Caller) -> None:
    if not (caller.has(REVIEWER) or caller.has(ADMIN)):
        raise Forbidden("Only reviewers can use the review queue.")


def _parse_enum(enum: Any, raw: str | None, name: str) -> Any:
    if raw is None or raw == "":
        return None
    try:
        return enum(raw)
    except ValueError:
        allowed = ", ".join(e.value for e in enum)
        raise BadRequest(f"{name} must be one of: {allowed}.") from None


def _note(body: dict[str, Any]) -> str | None:
    note = body.get("note")
    if note is None:
        return None
    if not isinstance(note, str) or len(note.strip()) > NOTE_MAX:
        raise BadRequest(f"note must be text of at most {NOTE_MAX} characters.")
    return note.strip() or None


class ReviewService:
    def __init__(
        self, repo: FoundRepository, cursors: CursorCodec, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._cursors = cursors
        self._clock = clock or SystemClock()

    def queue(
        self,
        caller: Caller,
        incident_id: str,
        *,
        item_type: str | None = None,
        status: str | None = None,
        limit: str | None = None,
        cursor: str | None = None,
    ) -> ReviewPage:
        _require_reviewer(caller)
        wanted_type = _parse_enum(ReviewItemType, item_type, "type")
        wanted_status = _parse_enum(ReviewStatus, status, "status") or ReviewStatus.OPEN
        page_size = parse_limit(limit)
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        scope = f"review:{incident_id}:{wanted_status}:{wanted_type or ''}"
        after = self._cursors.decode(scope, cursor) if cursor else None
        try:
            items, position = self._repo.list_review_items(
                incident_id, wanted_status, page_size, wanted_type, after
            )
        except ValueError:
            raise BadRequest("Cursor is invalid.") from None
        sources = {s.id: s for s in self._repo.list_sources(incident_id)}
        return ReviewPage(
            entries=[self._entry(item, sources) for item in items],
            next_cursor=self._cursors.encode(scope, position) if position else None,
        )

    def _entry(self, item: ReviewItem, sources: dict[str, Source]) -> ReviewEntry:
        if item.item_type == ReviewItemType.IDENTITY:
            proposal = self._repo.get_identity_proposal(item.incident_id, item.ref_id)
            ids = [proposal.person_a_id, proposal.person_b_id] if proposal else []
            found = {s.id: s for s in self._repo.get_subjects(ids)}
            return ReviewEntry(
                item=item,
                subject=self._repo.get_subject(item.subject_id) if item.subject_id else None,
                proposal=proposal,
                people=tuple(found[i] for i in ids if i in found),
            )
        if item.item_type == ReviewItemType.FINDING:
            investigation = self._repo.get_investigation(item.ref_id)
            claim = self._repo.get_claim(investigation.claim_id) if investigation else None
        else:
            investigation = None
            claim = self._repo.get_claim(item.ref_id)
        subject = self._repo.get_subject(claim.subject_id) if claim else None
        return ReviewEntry(
            item=item,
            claim=claim,
            subject=subject,
            source=sources.get(claim.source_id) if claim else None,
            investigation=investigation,
        )

    def resolve(
        self, caller: Caller, incident_id: str, review_id: str, body: dict[str, Any]
    ) -> ResolveResult:
        """Close a conflict, or release a held sensitive report and its alerts."""
        _require_reviewer(caller)
        if set(body) - {"note"}:
            raise BadRequest("The body may only hold a note.")
        note = _note(body)
        item = self._repo.get_review_item(incident_id, review_id)
        if item is None:
            raise NotFound("Review item not found.", review_id=review_id)
        if item.status != ReviewStatus.OPEN:
            raise VersionConflict("This item was already resolved.", review_id=review_id)
        if item.item_type not in (ReviewItemType.CONFLICT, ReviewItemType.HELD_ALERT):
            raise BadRequest(
                "Findings and identity proposals are decided on their own routes; "
                "this item cannot be closed here.",
                item_type=item.item_type.value,
            )
        released = 0
        if item.item_type == ReviewItemType.HELD_ALERT:
            released = self._release_alerts(item)
        done = self._repo.resolve_review_item(
            incident_id, review_id, caller.user_id, note, self._clock.now()
        )
        if done is None:
            raise VersionConflict("This item was already resolved.", review_id=review_id)
        return ResolveResult(done, alerts_released=released)

    def _release_alerts(self, item: ReviewItem) -> int:
        claim = self._repo.get_claim(item.ref_id)
        if claim is None:
            return 0
        released = 0
        for subscription in self._repo.list_subscriptions(claim.subject_id):
            # Only an alert still HELD moves, so a repeated release changes nothing.
            if self._repo.release_held_alert(
                subscription.id, claim.id, released_delivery(subscription)
            ):
                released += 1
        return released

    def review_finding(
        self, caller: Caller, investigation_id: str, body: dict[str, Any]
    ) -> Investigation:
        """Record a reviewer's verdict on a finding: ACCEPTED or DISPUTED, with a note."""
        _require_reviewer(caller)
        if set(body) - {"decision", "note"}:
            raise BadRequest("The body may only hold decision and note.")
        decision = _parse_enum(FindingReview, body.get("decision"), "decision")
        if decision is None:
            raise BadRequest("decision is required: ACCEPTED or DISPUTED.")
        note = _note(body)
        investigation = self._repo.get_investigation(investigation_id)
        if investigation is None:
            raise NotFound("Investigation not found.", investigation_id=investigation_id)
        if investigation.status not in TERMINAL_STATUSES or investigation.attribution is None:
            raise BadRequest("Only a recorded finding can be reviewed.")
        if investigation.review_status is not None:
            raise VersionConflict("This finding was already reviewed.")
        now = self._clock.now()
        reviewed = self._repo.update_investigation_if(
            investigation_id,
            investigation.status,
            {
                "review_status": decision,
                "reviewed_by": caller.user_id,
                "review_note": note,
                "reviewed_at": now,
            },
        )
        if reviewed is None:
            raise VersionConflict("This investigation changed; reload it.")
        self._repo.resolve_review_item(
            investigation.incident_id,
            review_item_id(ReviewItemType.FINDING, investigation_id),
            caller.user_id,
            note,
            now,
        )
        return reviewed
