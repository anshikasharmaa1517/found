"""Domain events from the table stream (design Sections 12.2 and 12.3).

The Pipe forwards stream records to the bus unchanged. Every consumer converts the
record with `from_stream`, so the event contract lives in one place. Delivery is at
least once and unordered, so consumers must be idempotent.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from found_core.domain.enums import SubjectType

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


DomainEvent = ClaimCreated | SubjectCreated
EVENT_MODELS: tuple[type[_Event], ...] = (ClaimCreated, SubjectCreated)


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


def from_stream(record: dict[str, Any]) -> DomainEvent | None:
    """Domain event for a stream record, or None for changes no consumer cares about."""
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
