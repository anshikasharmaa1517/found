"""In-memory repository with the same atomicity rules as the DynamoDB adapter.

Used by unit tests and local runs. Conditions are checked and applied under one lock,
which mirrors a DynamoDB transaction.
"""

import threading

from found_core.domain.enums import SubjectType
from found_core.domain.models import (
    Alert,
    Claim,
    Connection,
    IdemMarker,
    Organization,
    ReviewItem,
    Source,
    Subject,
    Subscription,
)
from found_core.ports.repository import (
    IdempotencyConflict,
    NamePosition,
    PublishPlan,
    SequenceConflict,
)


class InMemoryFoundRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.incidents: set[str] = set()
        self.organizations: dict[tuple[str, str], Organization] = {}
        self.sources: dict[str, Source] = {}
        self.subjects: dict[str, Subject] = {}
        self.claims: dict[str, Claim] = {}
        self.markers: dict[tuple[str, str], IdemMarker] = {}
        self.name_tokens: dict[str, set[str]] = {}
        self.subscriptions: dict[str, Subscription] = {}
        self.alerts: dict[tuple[str, str], Alert] = {}
        self.review_items: dict[str, ReviewItem] = {}
        self.connections: dict[str, Connection] = {}

    def add_incident(self, incident_id: str) -> None:
        self.incidents.add(incident_id)

    def incident_exists(self, incident_id: str) -> bool:
        return incident_id in self.incidents

    def add_organization(self, org: Organization) -> None:
        self.organizations[(org.incident_id, org.id)] = org

    def get_organization(self, incident_id: str, org_id: str) -> Organization | None:
        return self.organizations.get((incident_id, org_id))

    def get_idempotency(self, org_id: str, external_reference: str) -> IdemMarker | None:
        return self.markers.get((org_id, external_reference))

    def get_subject(self, subject_id: str) -> Subject | None:
        return self.subjects.get(subject_id)

    def get_subjects(self, subject_ids: list[str]) -> list[Subject]:
        return [self.subjects[s] for s in dict.fromkeys(subject_ids) if s in self.subjects]

    def list_subjects(
        self,
        incident_id: str,
        subject_type: SubjectType,
        limit: int,
        after: NamePosition | None = None,
    ) -> list[Subject]:
        start = (after.name_norm, after.subject_id) if after else None
        found = sorted(
            (
                s
                for s in self.subjects.values()
                if s.incident_id == incident_id
                and s.subject_type == subject_type
                and (start is None or (s.name_norm, s.id) > start)
            ),
            key=lambda s: (s.name_norm, s.id),
        )
        return found[:limit]

    def find_subject_ids_by_token(self, incident_id: str, prefix: str) -> list[str]:
        return sorted(
            sid
            for token, ids in self.name_tokens.items()
            if token.startswith(prefix)
            for sid in ids
            if self.subjects[sid].incident_id == incident_id
        )

    def ensure_source(self, source: Source) -> Source:
        with self._lock:
            return self.sources.setdefault(source.id, source)

    def list_sources(self, incident_id: str) -> list[Source]:
        return [s for s in self.sources.values() if s.incident_id == incident_id]

    def get_source(self, incident_id: str, source_id: str) -> Source | None:
        source = self.sources.get(source_id)
        return source if source and source.incident_id == incident_id else None

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

    def list_subscriptions(self, subject_id: str) -> list[Subscription]:
        found = [s for s in self.subscriptions.values() if s.subject_id == subject_id]
        return sorted(found, key=lambda s: s.id)

    def put_alert_if_absent(self, alert: Alert) -> bool:
        key = (alert.subscription_id, alert.claim_id)
        with self._lock:
            if key in self.alerts:
                return False
            self.alerts[key] = alert
            return True

    def put_review_item_if_absent(self, item: ReviewItem) -> bool:
        with self._lock:
            if item.id in self.review_items:
                return False
            self.review_items[item.id] = item
            return True

    def get_subscription(self, subject_id: str, subscription_id: str) -> Subscription | None:
        sub = self.subscriptions.get(subscription_id)
        return sub if sub and sub.subject_id == subject_id else None

    def save_subscription(self, subscription: Subscription) -> None:
        self.subscriptions[subscription.id] = subscription

    def list_user_subscriptions(self, user_id: str) -> list[Subscription]:
        found = [s for s in self.subscriptions.values() if s.user_id == user_id]
        return sorted(found, key=lambda s: s.id)

    def list_user_alerts(
        self, user_id: str, limit: int, after: dict[str, str] | None = None
    ) -> tuple[list[Alert], dict[str, str] | None]:
        def key(alert: Alert) -> tuple[str, str]:
            return (alert.created_at.isoformat(), alert.id)

        found = sorted(
            (a for a in self.alerts.values() if a.user_id == user_id), key=key, reverse=True
        )
        if after is not None:
            if set(after) != {"c", "i"}:
                raise ValueError("position does not belong to this listing")
            start = (after["c"], after["i"])
            found = [a for a in found if key(a) < start]
        page = found[:limit]
        if len(found) <= limit:
            return page, None
        last = page[-1]
        return page, {"c": last.created_at.isoformat(), "i": last.id}

    def put_connection(self, connection: Connection) -> None:
        self.connections[connection.id] = connection

    def get_connection(self, connection_id: str) -> Connection | None:
        return self.connections.get(connection_id)

    def delete_connection(self, connection_id: str) -> None:
        self.connections.pop(connection_id, None)

    def set_connection_incident(self, connection_id: str, incident_id: str) -> bool:
        with self._lock:
            current = self.connections.get(connection_id)
            if current is None:
                return False
            self.connections[connection_id] = current.model_copy(
                update={"incident_id": incident_id}
            )
            return True

    def list_incident_connections(self, incident_id: str) -> list[Connection]:
        return [c for c in self.connections.values() if c.incident_id == incident_id]

    def list_user_connections(self, user_id: str) -> list[Connection]:
        found = [c for c in self.connections.values() if c.user_id == user_id]
        return sorted(found, key=lambda c: (c.connected_at, c.id))
