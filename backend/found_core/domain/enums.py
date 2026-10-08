"""Enumerations and claim vocabularies shared across the domain."""

from enum import StrEnum


class SubjectType(StrEnum):
    PERSON = "PERSON"
    PLACE = "PLACE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SHELTER = "SHELTER"
    AID_POINT = "AID_POINT"
    HAZARD = "HAZARD"


class SourceType(StrEnum):
    POLICE = "POLICE"
    HOSPITAL = "HOSPITAL"
    NGO = "NGO"
    GOVERNMENT = "GOVERNMENT"
    SHELTER_OPERATOR = "SHELTER_OPERATOR"
    COMMUNITY = "COMMUNITY"


class Relation(StrEnum):
    FIRST = "FIRST"
    UPDATE = "UPDATE"
    HISTORICAL = "HISTORICAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_STATUS = "NOT_STATUS"


class Severity(StrEnum):
    INFO = "info"
    HIGH = "high"


class DeliveryStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    HELD = "HELD"
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ExtractionMethod(StrEnum):
    STRUCTURED_FORM = "structured_form"
    INTAKE_CONFIRMED = "textract+bedrock, human-confirmed"
    FIXTURE = "fixture"
    IMPORT = "import"


SUBJECT_ID_PREFIX: dict[SubjectType, str] = {
    SubjectType.PERSON: "per",
    SubjectType.PLACE: "plc",
    SubjectType.INFRASTRUCTURE: "inf",
    SubjectType.SHELTER: "shl",
    SubjectType.AID_POINT: "aid",
    SubjectType.HAZARD: "hzd",
}

CLAIM_TYPES: dict[SubjectType, frozenset[str]] = {
    SubjectType.PERSON: frozenset(
        {"MISSING", "FOUND_SAFE", "INJURED", "DECEASED", "SEEN_AT_LOCATION", "SHELTERED", "OTHER"}
    ),
    SubjectType.INFRASTRUCTURE: frozenset(
        {"ROAD_BLOCKED", "ROAD_OPEN", "BRIDGE_DAMAGED", "BRIDGE_OPEN", "OTHER"}
    ),
    SubjectType.SHELTER: frozenset({"SHELTER_OPEN", "SHELTER_FULL", "SHELTER_CLOSED", "OTHER"}),
    SubjectType.AID_POINT: frozenset({"AID_AVAILABLE", "AID_NEEDED", "AID_DELIVERED", "OTHER"}),
    SubjectType.HAZARD: frozenset(
        {"FLOODING", "LANDSLIDE", "WATER_RISING", "WATER_RECEDING", "OTHER"}
    ),
    SubjectType.PLACE: frozenset({"ACCESSIBLE", "INACCESSIBLE", "EVACUATED", "OTHER"}),
}

# Claim types that take part in status relations, per subject type.
STATUS_TYPES: dict[SubjectType, frozenset[str]] = {
    SubjectType.PERSON: frozenset({"MISSING", "FOUND_SAFE", "INJURED", "DECEASED"}),
    SubjectType.INFRASTRUCTURE: frozenset(
        {"ROAD_BLOCKED", "ROAD_OPEN", "BRIDGE_DAMAGED", "BRIDGE_OPEN"}
    ),
    SubjectType.SHELTER: frozenset({"SHELTER_OPEN", "SHELTER_FULL", "SHELTER_CLOSED"}),
}

SENSITIVE_CLAIM_TYPES: frozenset[str] = frozenset({"DECEASED"})
HIGH_SEVERITY_CLAIM_TYPES: frozenset[str] = frozenset({"DECEASED", "INJURED"})
