"""Persistence port used by the services. Adapters implement it for DynamoDB and memory."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from found_core.domain.enums import (
    DeliveryStatus,
    IntakeStatus,
    InvestigationStatus,
    ReviewItemType,
    ReviewStatus,
    SubjectType,
)
from found_core.domain.models import (
    Activity,
    Alert,
    Claim,
    Connection,
    IdemMarker,
    IdentityDecision,
    IdentityProposal,
    Incident,
    IntakeCandidate,
    IntakeJob,
    Investigation,
    InvestigationStep,
    Location,
    Organization,
    ReviewItem,
    Settings,
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

    def get_incident(self, incident_id: str) -> Incident | None: ...

    def put_incident(self, incident: Incident) -> None: ...

    def put_organization(self, org: Organization) -> None: ...

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

    def get_subscription(self, subject_id: str, subscription_id: str) -> Subscription | None: ...

    def save_subscription(self, subscription: Subscription) -> None: ...

    def list_user_subscriptions(self, user_id: str) -> list[Subscription]: ...

    def list_user_alerts(
        self, user_id: str, limit: int, after: dict[str, str] | None = None
    ) -> tuple[list[Alert], dict[str, str] | None]:
        """Newest first. The position is opaque to callers and only valid for this user."""
        ...

    def put_connection(self, connection: Connection) -> None: ...

    def get_connection(self, connection_id: str) -> Connection | None: ...

    def delete_connection(self, connection_id: str) -> None: ...

    def set_connection_incident(self, connection_id: str, incident_id: str) -> bool:
        """Point the connection at one incident's feed. False if the connection is gone."""
        ...

    def list_incident_connections(self, incident_id: str) -> list[Connection]: ...

    def list_user_connections(self, user_id: str) -> list[Connection]: ...

    def ensure_location(self, location: Location) -> Location: ...

    def list_locations(self, incident_id: str) -> list[Location]: ...

    def list_incident_claims(self, incident_id: str) -> list[Claim]: ...

    def get_review_item(self, incident_id: str, review_id: str) -> ReviewItem | None: ...

    def list_source_claims(
        self, source_id: str, limit: int, subject_id: str | None = None
    ) -> list[Claim]:
        """The source's claims, latest reported first, optionally about one subject."""
        ...

    def count_tool_call(self, investigation_id: str, cap: int) -> int | None:
        """Add one tool call while the run is RUNNING and under `cap`. Returns the count."""
        ...

    def latest_source_claim_id(self, source_id: str) -> str | None:
        """The claim at the top of the source's feed (latest reported time), if any."""
        ...

    def get_settings(self) -> Settings: ...

    def put_investigation(self, investigation: Investigation) -> None:
        """Store a new investigation. Raises ValueError if the id is taken."""
        ...

    def get_investigation(self, investigation_id: str) -> Investigation | None: ...

    def update_investigation_if(
        self,
        investigation_id: str,
        expected_status: InvestigationStatus,
        changes: dict[str, Any],
    ) -> Investigation | None:
        """Apply `changes` only while the status is `expected_status`.

        Returns the updated investigation, or None if it is gone or its status moved.
        Fields not named in `changes` are left as stored, so concurrent counters survive.
        """
        ...

    def find_cached_investigation(self, fingerprint: str) -> Investigation | None:
        """The newest COMPLETED or NEEDS_REVIEW run with this fingerprint."""
        ...

    def acquire_run_lock(
        self, claim_id: str, investigation_id: str, now: datetime, expires_at: datetime
    ) -> str:
        """Take the claim's run lock unless an unexpired one exists. Returns the holder."""
        ...

    def release_run_lock(self, claim_id: str, investigation_id: str) -> None:
        """Drop the lock if `investigation_id` still holds it."""
        ...

    def put_investigation_step(self, step: InvestigationStep) -> bool:
        """Store the step unless one exists at its (investigation, seq). True if stored."""
        ...

    def list_investigation_steps(self, investigation_id: str) -> list[InvestigationStep]:
        """Every step of the run, in order."""
        ...

    def list_review_items(
        self,
        incident_id: str,
        status: ReviewStatus,
        limit: int,
        item_type: ReviewItemType | None = None,
        after: dict[str, str] | None = None,
    ) -> tuple[list[ReviewItem], dict[str, str] | None]:
        """Most urgent first (priority, then age). The position is opaque to callers."""
        ...

    def resolve_review_item(
        self, incident_id: str, review_id: str, resolved_by: str, note: str | None, at: datetime
    ) -> ReviewItem | None:
        """Mark an OPEN item DONE. None if it is missing or already done."""
        ...

    def get_alert(self, subscription_id: str, claim_id: str) -> Alert | None: ...

    def release_held_alert(
        self, subscription_id: str, claim_id: str, status: DeliveryStatus
    ) -> bool:
        """Move a HELD alert to `status`. False if it is not held (any more)."""
        ...

    def transition_alert(
        self,
        subscription_id: str,
        claim_id: str,
        expected: DeliveryStatus,
        status: DeliveryStatus,
        *,
        channels: tuple[str, ...] = (),
        note: str | None = None,
        at: datetime | None = None,
    ) -> bool:
        """Move the alert from `expected` to `status`. False if it is not in `expected`.

        Only one caller wins a transition, which is what keeps texts and emails at most once.
        """
        ...

    def put_intake_job(self, job: IntakeJob) -> None: ...

    def get_intake_job(self, job_id: str) -> IntakeJob | None: ...

    def update_intake_job_if(
        self, job_id: str, expected: tuple[IntakeStatus, ...], changes: dict[str, Any]
    ) -> IntakeJob | None:
        """Apply `changes` only while the job's status is one of `expected`."""
        ...

    def put_intake_candidates(self, candidates: list[IntakeCandidate]) -> None:
        """Store each candidate unless one exists at its (job, idx)."""
        ...

    def list_intake_candidates(self, job_id: str) -> list[IntakeCandidate]: ...

    def get_intake_candidate(self, candidate_id: str) -> IntakeCandidate | None: ...

    def save_candidate_decision(self, candidate: IntakeCandidate) -> bool:
        """Store a decided candidate only if the stored one is still PENDING_REVIEW."""
        ...

    def put_identity_proposal_if_absent(self, proposal: IdentityProposal) -> bool:
        """Store the proposal unless one exists for its pair. True if stored."""
        ...

    def get_identity_proposal(self, incident_id: str, pair_key: str) -> IdentityProposal | None: ...

    def get_identity_decision(self, incident_id: str, pair_key: str) -> IdentityDecision | None: ...

    def save_identity_decision(self, decision: IdentityDecision, expected_version: int) -> bool:
        """Store the decision only if the stored version is `expected_version` (0: none yet).

        False if another decision was stored first.
        """
        ...

    def list_identity_decisions(self, incident_id: str, person_id: str) -> list[IdentityDecision]:
        """Current decisions on every pair that includes the person."""
        ...

    def put_activity(self, activity: Activity) -> None: ...

    def list_activity(self, incident_id: str, limit: int) -> list[Activity]:
        """Newest first."""
        ...

    def delete_incident_data(self, incident_id: str) -> int:
        """Remove every item that belongs to the incident, and nothing else.

        Budget, settings, other incidents and open connections are never touched.
        Returns how many items were removed.
        """
        ...
