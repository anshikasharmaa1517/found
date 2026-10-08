"""Validated input commands."""

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from found_core.domain.enums import CLAIM_TYPES, ExtractionMethod, SourceType, SubjectType
from found_core.domain.errors import ValidationFailed

REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def parse_reported_at(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 time with offset into UTC. Unknown stays None; it is never guessed."""
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("reported_at must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("reported_at must include a UTC offset")
    return parsed.astimezone(UTC)


class NewSubject(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    age: int | None = Field(default=None, ge=0, le=120)
    notes: str | None = Field(default=None, max_length=500)


class SubjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SubjectType
    id: str | None = None
    new: NewSubject | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "SubjectRef":
        if (self.id is None) == (self.new is None):
            raise ValueError("subject needs exactly one of id or new")
        if self.new is not None and self.new.age is not None and self.type != SubjectType.PERSON:
            raise ValueError("age is only valid for PERSON subjects")
        return self


class PublishCommand(BaseModel):
    """A report published by an organization.

    Organization fields come from the caller's verified identity, never the request body.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    incident_id: str
    org_id: str
    org_name: str = Field(min_length=1, max_length=120)
    org_type: SourceType
    actor: str
    subject: SubjectRef
    claim_type: str
    value: str | None = Field(default=None, max_length=500)
    original_text: str = Field(min_length=1, max_length=4000)
    external_reference: str
    reported_at: str | None = None
    extraction_method: ExtractionMethod = ExtractionMethod.STRUCTURED_FORM

    @model_validator(mode="after")
    def _check(self) -> "PublishCommand":
        if self.claim_type not in CLAIM_TYPES[self.subject.type]:
            raise ValueError(f"claim_type {self.claim_type} is not valid for {self.subject.type}")
        if not REFERENCE_PATTERN.match(self.external_reference):
            raise ValueError("external_reference must be 1 to 64 of [A-Za-z0-9._-]")
        parse_reported_at(self.reported_at)
        return self

    def reported_at_utc(self) -> datetime | None:
        return parse_reported_at(self.reported_at)

    def payload(self) -> dict[str, Any]:
        """The content that defines this report, used for idempotency."""
        return {
            "incident_id": self.incident_id,
            "subject": self.subject.model_dump(mode="json", exclude_none=True),
            "claim_type": self.claim_type,
            "value": self.value,
            "original_text": self.original_text,
            "reported_at": self.reported_at,
            "extraction_method": self.extraction_method.value,
        }

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "PublishCommand":
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = [
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                for err in exc.errors(include_url=False)
            ]
            raise ValidationFailed("Report is invalid.", errors=errors) from exc


class FollowCommand(BaseModel):
    """Channels for following one person. In-app delivery is always on."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    channel_sms: bool = False
    channel_email: bool = False
    phone_e164: str | None = Field(default=None, max_length=16)
    email: str | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def _check(self) -> "FollowCommand":
        if self.phone_e164 is not None and not E164_PATTERN.match(self.phone_e164):
            raise ValueError("phone_e164 must look like +919876543210")
        if self.email is not None and not EMAIL_PATTERN.match(self.email):
            raise ValueError("email is not a valid address")
        if self.channel_sms and self.phone_e164 is None:
            raise ValueError("SMS alerts need phone_e164")
        if self.channel_email and self.email is None:
            raise ValueError("email alerts need email")
        return self

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "FollowCommand":
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = [
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                for err in exc.errors(include_url=False)
            ]
            raise ValidationFailed("Subscription is invalid.", errors=errors) from exc
