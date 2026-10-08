"""Persistence port used by the services. Adapters implement it for DynamoDB and memory."""

from dataclasses import dataclass
from typing import Protocol

from found_core.domain.enums import SubjectType
from found_core.domain.models import (
    Alert,
    Claim,
    IdemMarker,
    Organization,
    ReviewItem,
    Source,
    Subject,
    Subscription,
)


@dataclass(frozen=True)
class NamePosition:
    """A place in an incident's subjects sorted by normalized name, then id."""

    name_norm: str
    subject_id: str


class IdempotencyConflict(Exception):
    """The (organization, reference) marker already exists."""


class SequenceConflict(Exception):
    """The subject's sequence moved since it was read."""


@dataclass(frozen=True)
class PublishPlan:
    """Everything one publish writes, applied atomically."""

    marker: IdemMarker
    subject: Subject
    expected_seq: int
    create_subject: bool
    claim: Claim
    name_tokens: tuple[str, ...] = ()


class FoundRepository(Protocol):
    def incident_exists(self, incident_id: str) -> bool: ...

    def get_organization(self, incident_id: str, org_id: str) -> Organization | None: ...

    def get_idempotency(self, org_id: str, external_reference: str) -> IdemMarker | None: ...

    def get_subject(self, subject_id: str) -> Subject | None: ...

    def get_subjects(self, subject_ids: list[str]) -> list[Subject]: ...

    def list_subjects(
        self,
        incident_id: str,
        subject_type: SubjectType,
        limit: int,
        after: NamePosition | None = None,
    ) -> list[Subject]: ...

    def find_subject_ids_by_token(self, incident_id: str, prefix: str) -> list[str]: ...

    def ensure_source(self, source: Source) -> Source: ...

    def list_sources(self, incident_id: str) -> list[Source]: ...

    def get_source(self, incident_id: str, source_id: str) -> Source | None: ...

    def publish_claim_tx(self, plan: PublishPlan) -> Claim: ...

    def get_claim(self, claim_id: str) -> Claim | None: ...

    def list_subject_claims(
        self, subject_id: str, before_seq: int | None = None
    ) -> list[Claim]: ...

    def list_subscriptions(self, subject_id: str) -> list[Subscription]: ...

    def put_alert_if_absent(self, alert: Alert) -> bool:
        """Store the alert unless one exists for its (subscription, claim). True if stored."""
        ...

    def put_review_item_if_absent(self, item: ReviewItem) -> bool:
        """Store the item unless one exists for its (type, ref). True if stored."""
        ...
