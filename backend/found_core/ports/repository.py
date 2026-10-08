"""Persistence port used by the services. Adapters implement it for DynamoDB and memory."""

from dataclasses import dataclass
from typing import Protocol

from found_core.domain.models import (
    Claim,
    IdemMarker,
    Source,
    Subject,
)


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


    def get_idempotency(self, org_id: str, external_reference: str) -> IdemMarker | None: ...

    def get_subject(self, subject_id: str) -> Subject | None: ...


    def ensure_source(self, source: Source) -> Source: ...

    def list_sources(self, incident_id: str) -> list[Source]: ...


    def publish_claim_tx(self, plan: PublishPlan) -> Claim: ...

    def get_claim(self, claim_id: str) -> Claim | None: ...

    def list_subject_claims(
        self, subject_id: str, before_seq: int | None = None
    ) -> list[Claim]: ...
