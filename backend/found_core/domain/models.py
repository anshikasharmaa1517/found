"""Stored entities. All are immutable value objects."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from found_core.domain.enums import (
    DeliveryStatus,
    ExtractionMethod,
    Relation,
    Severity,
    SourceType,
    SubjectType,
)
from found_core.domain.normalize import name_tokens


class _Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Source(_Entity):
    id: str
    incident_id: str
    name: str
    name_norm: str
    source_type: SourceType
    organization_id: str | None = None


class Subject(_Entity):
    """A person, place or other thing that claims are about. Deliberately has no status."""

    id: str
    incident_id: str
    subject_type: SubjectType
    display_name: str
    name_norm: str
    age: int | None = None
    notes: str | None = None
    claim_seq: int = 0

    def tokens(self) -> list[str]:
        return name_tokens(self.display_name)


class Claim(_Entity):
    id: str
    incident_id: str
    subject_id: str
    subject_type: SubjectType
    source_id: str
    seq: int
    claim_type: str
    value: str | None = None
    original_text: str
    external_reference: str
    reported_at: datetime | None = None
    reported_at_raw: str | None = None
    ingested_at: datetime
    extraction_method: ExtractionMethod
    payload_hash: str
    mentioned_source_ids: tuple[str, ...] = ()
    created_by: str


class Subscription(_Entity):
    id: str
    subject_id: str
    user_id: str
    channel_inapp: bool = True
    channel_sms: bool = False
    channel_email: bool = False


class Alert(_Entity):
    """One per (subscription, claim). The key, not the id, enforces that."""

    id: str
    incident_id: str
    subject_id: str
    subscription_id: str
    claim_id: str
    user_id: str
    relation: Relation
    severity: Severity
    message: str
    delivery_status: DeliveryStatus
    held_reason: str | None = None
    created_at: datetime


class IdemMarker(_Entity):
    org_id: str
    external_reference: str
    claim_id: str
    payload_hash: str
