"""Pure status rules shared by the watcher and the read models.

Priors for a claim are always the claims about the same subject with a lower sequence
number. Sequence numbers are committed atomically with claims, so these rules give the
same answer regardless of event order or duplicate deliveries.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from found_core.domain.enums import (
    HIGH_SEVERITY_CLAIM_TYPES,
    SENSITIVE_CLAIM_TYPES,
    STATUS_TYPES,
    DeliveryStatus,
    Relation,
    ReviewItemType,
    Severity,
    SubjectType,
)
from found_core.domain.models import Claim, Subscription

_EARLIEST = datetime.min.replace(tzinfo=UTC)

PLAIN_STATUS: dict[str, str] = {
    "MISSING": "missing",
    "FOUND_SAFE": "found safe",
    "INJURED": "injured",
    "DECEASED": "deceased",
    "ROAD_BLOCKED": "road blocked",
    "ROAD_OPEN": "road open",
    "BRIDGE_DAMAGED": "bridge damaged",
    "BRIDGE_OPEN": "bridge open",
    "SHELTER_OPEN": "shelter open",
    "SHELTER_FULL": "shelter full",
    "SHELTER_CLOSED": "shelter closed",
}


def status_claims(claims: Sequence[Claim], subject_type: SubjectType) -> list[Claim]:
    types = STATUS_TYPES.get(subject_type, frozenset())
    return [c for c in claims if c.claim_type in types]


def report_order(claim: Claim) -> tuple[bool, datetime, int]:
    # Dated claims rank above undated ones; ties break on arrival order.
    return (claim.reported_at is not None, claim.reported_at or _EARLIEST, claim.seq)


def latest_by_report_time(claims: Sequence[Claim]) -> Claim:
    return max(claims, key=report_order)


def classify(incoming: Claim, priors: Sequence[Claim]) -> Relation:
    if incoming.claim_type not in STATUS_TYPES.get(incoming.subject_type, frozenset()):
        return Relation.NOT_STATUS
    prior_status = status_claims(priors, incoming.subject_type)
    if not prior_status:
        return Relation.FIRST
    previous = latest_by_report_time(prior_status)
    if incoming.reported_at is None or previous.reported_at is None:
        return Relation.NEEDS_REVIEW
    if incoming.reported_at > previous.reported_at:
        return Relation.UPDATE
    if incoming.reported_at < previous.reported_at:
        return Relation.HISTORICAL
    return Relation.NEEDS_REVIEW


@dataclass(frozen=True)
class AlertDecision:
    alert: bool
    kind: str | None = None
    severity: Severity = Severity.INFO
    review: bool = False


NO_ALERT = AlertDecision(alert=False)


def decide_alert(incoming: Claim, priors: Sequence[Claim], relation: Relation) -> AlertDecision:
    if relation == Relation.NOT_STATUS:
        return NO_ALERT
    severity = (
        Severity.HIGH if incoming.claim_type in HIGH_SEVERITY_CLAIM_TYPES else Severity.INFO
    )
    if relation == Relation.FIRST:
        return AlertDecision(alert=True, kind="First report", severity=severity)
    prior_status = status_claims(priors, incoming.subject_type)
    if relation == Relation.NEEDS_REVIEW:
        if any(c.claim_type != incoming.claim_type for c in prior_status):
            return AlertDecision(
                alert=True, kind="Reports need review", severity=Severity.HIGH, review=True
            )
        return NO_ALERT
    previous = latest_by_report_time(prior_status)
    if incoming.claim_type == previous.claim_type:
        return NO_ALERT
    kind = "Newer report" if relation == Relation.UPDATE else "Earlier report received"
    return AlertDecision(alert=True, kind=kind, severity=severity)


def delivery_for(claim_type: str, subscription: Subscription) -> tuple[DeliveryStatus, str | None]:
    """Sensitive statuses are held for a reviewer before any SMS or email."""
    if claim_type in SENSITIVE_CLAIM_TYPES:
        return DeliveryStatus.HELD, "SENSITIVE_STATUS"
    if not (subscription.channel_sms or subscription.channel_email):
        return DeliveryStatus.NOT_REQUIRED, None
    return DeliveryStatus.PENDING, None


# 1 is the most urgent. A family may be waiting on a held sensitive alert.
REVIEW_PRIORITY: dict[ReviewItemType, int] = {
    ReviewItemType.HELD_ALERT: 1,
    ReviewItemType.CONFLICT: 2,
}


def alert_message(kind: str, subject_name: str, source_name: str, claim: Claim) -> str:
    if claim.claim_type in SENSITIVE_CLAIM_TYPES:
        return (
            f"A sensitive report about {subject_name} was received. "
            "A coordinator will contact you."
        )
    status = PLAIN_STATUS.get(claim.claim_type, claim.claim_type.lower().replace("_", " "))
    when = claim.reported_at.isoformat() if claim.reported_at else "unknown"
    return (
        f"{kind} for {subject_name}: {source_name} says {status}. "
        f"Reported time: {when}. Earlier reports are retained."
    )


@dataclass(frozen=True)
class CitedSummary:
    label: str
    cited_claim_id: str | None
    basis: str
    conflicts: list[str] = field(default_factory=list)
    needs_review: bool = False


def summarize(claims: Sequence[Claim], subject_type: SubjectType) -> CitedSummary:
    """Current label for a subject, always citing the claim it is based on."""
    ordered = sorted(claims, key=lambda c: c.seq)
    statuses = status_claims(ordered, subject_type)
    if not statuses:
        return CitedSummary(
            label="No status reports", cited_claim_id=None, basis="No status reports yet"
        )
    latest = latest_by_report_time(statuses)
    latest_per_source: dict[str, Claim] = {}
    for claim in statuses:
        current = latest_per_source.get(claim.source_id)
        if current is None or report_order(claim) > report_order(current):
            latest_per_source[claim.source_id] = claim
    conflicts = [
        c.id
        for c in latest_per_source.values()
        if c.source_id != latest.source_id and c.claim_type != latest.claim_type
    ]
    needs_review = any(
        classify(c, ordered[:i]) == Relation.NEEDS_REVIEW
        and decide_alert(c, ordered[:i], Relation.NEEDS_REVIEW).review
        for i, c in enumerate(ordered)
    )
    status = PLAIN_STATUS.get(latest.claim_type, latest.claim_type.lower())
    basis = (
        "Latest dated status report"
        if latest.reported_at is not None
        else "Latest status report, reported time unknown"
    )
    return CitedSummary(
        label=f"Reported {status}",
        cited_claim_id=latest.id,
        basis=basis,
        conflicts=conflicts,
        needs_review=needs_review,
    )


def relations(claims: Sequence[Claim]) -> dict[str, Relation]:
    """Relation of every claim to the claims about the same subject that arrived before it."""
    ordered = sorted(claims, key=lambda c: c.seq)
    return {c.id: classify(c, ordered[:i]) for i, c in enumerate(ordered)}


# Reported ages are estimates, so an age filter matches within this many years.
AGE_TOLERANCE = 2


def age_matches(age: int | None, wanted: int) -> bool:
    """People with no recorded age are kept: hiding a possible match costs more than noise."""
    return age is None or abs(age - wanted) <= AGE_TOLERANCE
