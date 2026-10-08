"""Reacts to each stored claim: classify it, alert followers once, queue reviews.

Design Sections 5.1 (step 5), 6.2 and 9.6. Events arrive at least once and in any order.
Every write here is put-if-absent under a key derived from the claim, so a repeated or
late delivery does nothing new, and a retry after a crash completes the missing writes.
"""

from dataclasses import dataclass, field

from found_core.domain.enums import (
    SENSITIVE_CLAIM_TYPES,
    DeliveryStatus,
    Relation,
    ReviewItemType,
)
from found_core.domain.ids import new_id, review_item_id
from found_core.domain.models import Alert, Claim, ReviewItem
from found_core.domain.rules import (
    REVIEW_PRIORITY,
    AlertDecision,
    alert_message,
    classify,
    decide_alert,
    delivery_for,
)
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository


@dataclass(frozen=True)
class WatchResult:
    claim_id: str
    relation: Relation | None = None
    alerts_created: int = 0
    review_items_created: list[ReviewItemType] = field(default_factory=list)
    skipped_reason: str | None = None


class WatchService:
    def __init__(self, repo: FoundRepository, clock: Clock | None = None) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()

    def on_claim_created(self, subject_id: str, claim_id: str, seq: int) -> WatchResult:
        # Consistent read of claims 1..seq. Sequences commit with their claims, so every
        # prior is already visible and the answer does not depend on delivery order.
        claims = self._repo.list_subject_claims(subject_id, before_seq=seq + 1)
        incoming = next((c for c in claims if c.seq == seq), None)
        if incoming is None:
            # Only a demo reset removes claims; the event outlived its claim.
            return WatchResult(claim_id=claim_id, skipped_reason="CLAIM_NOT_FOUND")
        if incoming.id != claim_id:
            raise ValueError(f"seq {seq} of {subject_id} is {incoming.id}, not {claim_id}")

        priors = [c for c in claims if c.seq < seq]
        relation = classify(incoming, priors)
        decision = decide_alert(incoming, priors, relation)

        reviews: list[ReviewItemType] = []
        if decision.review and self._open_review(incoming, ReviewItemType.CONFLICT):
            reviews.append(ReviewItemType.CONFLICT)

        created, held = self._alert_followers(incoming, relation, decision)
        # A sensitive report always waits for a reviewer, with or without followers:
        # releasing it frees its alerts and shows it in full to everyone.
        sensitive = incoming.claim_type in SENSITIVE_CLAIM_TYPES
        if (held or sensitive) and self._open_review(incoming, ReviewItemType.HELD_ALERT):
            reviews.append(ReviewItemType.HELD_ALERT)

        return WatchResult(
            claim_id=claim_id,
            relation=relation,
            alerts_created=created,
            review_items_created=reviews,
        )

    def _alert_followers(
        self, claim: Claim, relation: Relation, decision: AlertDecision
    ) -> tuple[int, bool]:
        """Returns how many alerts were new, and whether any alert for this claim is held."""
        if not decision.alert or decision.kind is None:
            return 0, False
        followers = [s for s in self._repo.list_subscriptions(claim.subject_id) if s.active]
        if not followers:
            return 0, False

        subject = self._repo.get_subject(claim.subject_id)
        source = self._repo.get_source(claim.incident_id, claim.source_id)
        subject_name = subject.display_name if subject else "this person"
        source_name = source.name if source else "A source"
        message = alert_message(decision.kind, subject_name, source_name, claim)

        created, held = 0, False
        for subscription in followers:
            status, held_reason = delivery_for(claim.claim_type, subscription)
            held = held or status == DeliveryStatus.HELD
            alert = Alert(
                id=new_id("alr"),
                incident_id=claim.incident_id,
                subject_id=claim.subject_id,
                subscription_id=subscription.id,
                claim_id=claim.id,
                user_id=subscription.user_id,
                relation=relation,
                severity=decision.severity,
                message=message,
                delivery_status=status,
                held_reason=held_reason,
                created_at=self._clock.now(),
            )
            if self._repo.put_alert_if_absent(alert):
                created += 1
        return created, held

    def _open_review(self, claim: Claim, item_type: ReviewItemType) -> bool:
        item = ReviewItem(
            id=review_item_id(item_type, claim.id),
            incident_id=claim.incident_id,
            item_type=item_type,
            ref_id=claim.id,
            subject_id=claim.subject_id,
            priority=REVIEW_PRIORITY[item_type],
            created_at=self._clock.now(),
        )
        return self._repo.put_review_item_if_absent(item)
