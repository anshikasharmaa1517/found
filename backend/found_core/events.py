"""Domain events from the table stream (design Sections 12.2 and 12.3).

The Pipe forwards stream records to the bus unchanged. Every consumer converts the
record with `from_stream`, so the event contract lives in one place. Delivery is at
least once and unordered, so consumers must be idempotent.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from found_core.domain.enums import (
    DeliveryStatus,
    InvestigationStatus,
    ReviewItemType,
    Severity,
    StepKind,
    SubjectType,
)

EVENT_SOURCE = "found.ddb"
EVENT_DETAIL_TYPE = "found.ddb.change"


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    event_id: str
    incident_id: str
    occurred_at: datetime


class ClaimCreated(_Event):
    type: Literal["claim.created"] = "claim.created"
    subject_id: str
    subject_type: SubjectType
    claim_id: str
    seq: int
    source_id: str


class SubjectCreated(_Event):
    type: Literal["subject.created"] = "subject.created"
    subject_id: str
    subject_type: SubjectType


class AlertCreated(_Event):
    type: Literal["alert.created"] = "alert.created"
    alert_id: str
    user_id: str
    subject_id: str
    subscription_id: str
    claim_id: str
    severity: Severity
    message: str
    delivery_status: DeliveryStatus


class AlertReleased(_Event):
    """A reviewer released a held alert, so it is now due for text or email."""

    type: Literal["alert.released"] = "alert.released"
    alert_id: str
    user_id: str
    subject_id: str
    subscription_id: str
    claim_id: str


class ReviewCreated(_Event):
    type: Literal["review.created"] = "review.created"
    review_id: str
    item_type: ReviewItemType
    ref_id: str
    subject_id: str | None = None
    priority: int


class InvestigationStepCreated(_Event):
    type: Literal["investigation.step"] = "investigation.step"
    investigation_id: str
    seq: int
    kind: StepKind
    tool_name: str | None = None
    summary: str | None = None


class InvestigationUpdated(_Event):
    """The run's status moved. Counter updates that keep the status are not events."""

    type: Literal["investigation.updated"] = "investigation.updated"
    investigation_id: str
    claim_id: str
    status: InvestigationStatus


DomainEvent = (
    ClaimCreated
    | SubjectCreated
    | AlertCreated
    | AlertReleased
    | ReviewCreated
    | InvestigationStepCreated
    | InvestigationUpdated
)
EVENT_MODELS: tuple[type[_Event], ...] = (
    ClaimCreated,
    SubjectCreated,
    AlertCreated,
    AlertReleased,
    ReviewCreated,
    InvestigationStepCreated,
    InvestigationUpdated,
)


class NotADomainEvent(ValueError):
    """The envelope or record is not one this module understands."""


def _number(text: str) -> int | Decimal:
    value = Decimal(text)
    return int(value) if value == value.to_integral_value() else value


def from_attribute(value: dict[str, Any]) -> Any:
    """Convert one value in DynamoDB JSON (`{"S": "x"}`) to plain Python."""
    if len(value) != 1:
        raise NotADomainEvent("attribute value must have exactly one type key")
    kind, raw = next(iter(value.items()))
    match kind:
        case "S" | "B":
            return raw
        case "N":
            return _number(raw)
        case "BOOL":
            return bool(raw)
        case "NULL":
            return None
        case "L":
            return [from_attribute(v) for v in raw]
        case "M":
            return from_image(raw)
        case "SS" | "BS":
            return set(raw)
        case "NS":
            return {_number(v) for v in raw}
    raise NotADomainEvent(f"unknown attribute type {kind!r}")


def from_image(image: dict[str, Any]) -> dict[str, Any]:
    return {name: from_attribute(value) for name, value in image.items()}


def _stream_time(record: dict[str, Any]) -> datetime:
    seconds = record.get("dynamodb", {}).get("ApproximateCreationDateTime")
    if seconds is None:
        raise NotADomainEvent("stream record has no creation time")
    return datetime.fromtimestamp(float(seconds), tz=UTC)


def _investigation_changed(record: dict[str, Any]) -> InvestigationUpdated | None:
    change = record.get("dynamodb", {})
    new = from_image(change.get("NewImage") or {})
    old = from_image(change.get("OldImage") or {})
    if new.get("entity_type") != "INVESTIGATION" or new.get("status") == old.get("status"):
        return None
    return InvestigationUpdated(
        event_id=str(record.get("eventID", "")),
        incident_id=new["incident_id"],
        investigation_id=new["id"],
        claim_id=new["claim_id"],
        status=new["status"],
        occurred_at=_stream_time(record),
    )


def _alert_released(record: dict[str, Any]) -> AlertReleased | None:
    change = record.get("dynamodb", {})
    new = from_image(change.get("NewImage") or {})
    old = from_image(change.get("OldImage") or {})
    if (
        new.get("entity_type") != "ALERT"
        or old.get("delivery_status") != DeliveryStatus.HELD
        or new.get("delivery_status") != DeliveryStatus.PENDING
    ):
        return None
    return AlertReleased(
        event_id=str(record.get("eventID", "")),
        incident_id=new["incident_id"],
        alert_id=new["id"],
        user_id=new["user_id"],
        subject_id=new["subject_id"],
        subscription_id=new["subscription_id"],
        claim_id=new["claim_id"],
        occurred_at=_stream_time(record),
    )


def from_stream(record: dict[str, Any]) -> DomainEvent | None:
    """Domain event for a stream record, or None for changes no consumer cares about."""
    if record.get("eventName") == "MODIFY":
        return _investigation_changed(record) or _alert_released(record)
    if record.get("eventName") != "INSERT":
        return None
    image = from_image(record.get("dynamodb", {}).get("NewImage") or {})
    event_id = str(record.get("eventID", ""))
    match image.get("entity_type"):
        case "CLAIM":
            return ClaimCreated(
                event_id=event_id,
                incident_id=image["incident_id"],
                subject_id=image["subject_id"],
                subject_type=image["subject_type"],
                claim_id=image["id"],
                seq=image["seq"],
                source_id=image["source_id"],
                occurred_at=image["ingested_at"],
            )
        case "ALERT":
            return AlertCreated(
                event_id=event_id,
                incident_id=image["incident_id"],
                alert_id=image["id"],
                user_id=image["user_id"],
                subject_id=image["subject_id"],
                subscription_id=image["subscription_id"],
                claim_id=image["claim_id"],
                severity=image["severity"],
                message=image["message"],
                delivery_status=image["delivery_status"],
                occurred_at=image["created_at"],
            )
        case "REVIEW_ITEM":
            return ReviewCreated(
                event_id=event_id,
                incident_id=image["incident_id"],
                review_id=image["id"],
                item_type=image["item_type"],
                ref_id=image["ref_id"],
                subject_id=image.get("subject_id"),
                priority=image["priority"],
                occurred_at=image["created_at"],
            )
        case "INVESTIGATION_STEP":
            return InvestigationStepCreated(
                event_id=event_id,
                incident_id=image["incident_id"],
                investigation_id=image["investigation_id"],
                seq=image["seq"],
                kind=image["kind"],
                tool_name=image.get("tool_name"),
                summary=image.get("output_summary"),
                occurred_at=image["created_at"],
            )
        case "SUBJECT":
            return SubjectCreated(
                event_id=event_id,
                incident_id=image["incident_id"],
                subject_id=image["id"],
                subject_type=image["subject_type"],
                occurred_at=_stream_time(record),
            )
    return None


def from_bus_event(event: dict[str, Any]) -> DomainEvent | None:
    """Unwrap the EventBridge envelope a rule target receives."""
    if event.get("source") != EVENT_SOURCE or event.get("detail-type") != EVENT_DETAIL_TYPE:
        raise NotADomainEvent("event did not come from the table stream pipe")
    detail = event.get("detail")
    if not isinstance(detail, dict):
        raise NotADomainEvent("event has no detail")
    return from_stream(detail)
