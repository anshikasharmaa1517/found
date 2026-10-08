"""Stored entities. All are immutable value objects."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from found_core.domain.enums import (
    Attribution,
    Comparison,
    DeliveryStatus,
    ExtractionMethod,
    FindingReview,
    InvestigationMode,
    InvestigationStatus,
    Relation,
    ReviewItemType,
    ReviewStatus,
    Severity,
    SourceType,
    SubjectType,
)
from found_core.domain.normalize import name_tokens


class _Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Organization(_Entity):
    """An organization registered for one incident. The publisher's token carries its id."""

    id: str
    incident_id: str
    name: str
    name_norm: str
    org_type: SourceType


class Source(_Entity):
    id: str
    incident_id: str
    name: str
    name_norm: str
    source_type: SourceType
    organization_id: str | None = None


class Location(_Entity):
    """A reported place. Same incident, name and rounded coordinates give the same id."""

    id: str
    incident_id: str
    name: str
    name_norm: str
    lat: float | None = None
    lon: float | None = None


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
    location_id: str | None = None
    created_by: str


class Subscription(_Entity):
    id: str
    subject_id: str
    user_id: str
    channel_inapp: bool = True
    channel_sms: bool = False
    channel_email: bool = False
    phone_e164: str | None = None
    email: str | None = None
    active: bool = True
    created_at: datetime | None = None


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


class ReviewItem(_Entity):
    """One per (item_type, ref_id); the id is derived from both."""

    id: str
    incident_id: str
    item_type: ReviewItemType
    ref_id: str
    subject_id: str | None = None
    status: ReviewStatus = ReviewStatus.OPEN
    priority: int
    created_at: datetime


class Connection(_Entity):
    """An open WebSocket. Roles are copied from the verified token at connect time."""

    id: str
    user_id: str
    groups: tuple[str, ...] = ()
    org_id: str | None = None
    incident_id: str | None = None
    connected_at: datetime
    expires_at: datetime


class Citation(_Entity):
    claim_id: str
    excerpt: str


class Investigation(_Entity):
    """One provenance run on one claim. Only code moves it between statuses."""

    id: str
    incident_id: str
    claim_id: str
    fingerprint: str
    mode: InvestigationMode
    status: InvestigationStatus
    model_id: str
    prompt_version: str
    agent_version: str
    attribution: Attribution | None = None
    referenced_source_id: str | None = None
    comparison: Comparison | None = None
    summary: str | None = None
    citations: tuple[Citation, ...] = ()
    outcome_reasons: tuple[str, ...] = ()
    tool_calls: int = 0
    model_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_source: str | None = None
    failure_reason: str | None = None
    review_status: FindingReview | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    reviewed_at: datetime | None = None
    created_by: str
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @field_validator("mode")
    @classmethod
    def _stored_mode(cls, mode: InvestigationMode) -> InvestigationMode:
        if mode == InvestigationMode.CACHED:
            raise ValueError("CACHED labels a response; a stored run is LIVE or REPLAYED")
        return mode


class Settings(_Entity):
    """Admin switches. Caps left unset fall back to the deployed configuration."""

    live_enabled: bool = False
    run_cap: int | None = None
    model_call_cap: int | None = None


class IdemMarker(_Entity):
    org_id: str
    external_reference: str
    claim_id: str
    payload_hash: str
