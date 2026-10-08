"""In-memory repository with the same atomicity rules as the DynamoDB adapter.

Used by unit tests and local runs. Conditions are checked and applied under one lock,
which mirrors a DynamoDB transaction.
"""

import threading

from found_core.domain.models import (
    Alert,
    Claim,
    IdemMarker,
    Source,
    Subject,
    Subscription,
)
from found_core.ports.repository import (
    IdempotencyConflict,
    PublishPlan,
    SequenceConflict,
)


class InMemoryFoundRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.incidents: set[str] = set()
        self.sources: dict[str, Source] = {}
        self.subjects: dict[str, Subject] = {}
        self.claims: dict[str, Claim] = {}
        self.markers: dict[tuple[str, str], IdemMarker] = {}
        self.name_tokens: dict[str, set[str]] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.alerts: dict[tuple[str, str], Alert] = {}

    def add_incident(self, incident_id: str) -> None:
        self.incidents.add(incident_id)

    def incident_exists(self, incident_id: str) -> bool:
        return incident_id in self.incidents

    def get_idempotency(self, org_id: str, external_reference: str) -> IdemMarker | None:
        return self.markers.get((org_id, external_reference))

    def get_subject(self, subject_id: str) -> Subject | None:
        return self.subjects.get(subject_id)

    def ensure_source(self, source: Source) -> Source:
        with self._lock:
            return self.sources.setdefault(source.id, source)

    def list_sources(self, incident_id: str) -> list[Source]:
        return [s for s in self.sources.values() if s.incident_id == incident_id]

    def publish_claim_tx(self, plan: PublishPlan) -> Claim:
        key = (plan.marker.org_id, plan.marker.external_reference)
        with self._lock:
            if key in self.markers:
                raise IdempotencyConflict()
            current = self.subjects.get(plan.subject.id)
            if plan.create_subject:
                if current is not None:
                    raise SequenceConflict()
            elif current is None or current.claim_seq != plan.expected_seq:
                raise SequenceConflict()
            if plan.claim.source_id not in self.sources:
                raise ValueError("source must exist before publish")
            self.markers[key] = plan.marker
            self.subjects[plan.subject.id] = plan.subject
            self.claims[plan.claim.id] = plan.claim
            for token in plan.name_tokens:
                self.name_tokens.setdefault(token, set()).add(plan.subject.id)
            return plan.claim

    def get_claim(self, claim_id: str) -> Claim | None:
        return self.claims.get(claim_id)

    def list_subject_claims(self, subject_id: str, before_seq: int | None = None) -> list[Claim]:
        found = [
            c
            for c in self.claims.values()
            if c.subject_id == subject_id and (before_seq is None or c.seq < before_seq)
        ]
        return sorted(found, key=lambda c: c.seq)

    def add_subscription(self, subscription: Subscription) -> None:
        self.subscriptions[subscription.id] = subscription
