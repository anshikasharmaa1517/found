"""In-memory repository with the same atomicity rules as the DynamoDB adapter.

Used by unit tests and local runs. Conditions are checked and applied under one lock,
which mirrors a DynamoDB transaction.
"""

import threading
from dataclasses import replace
from datetime import datetime
from typing import Any

from found_core.domain.enums import (
    CandidateStatus,
    DeliveryStatus,
    IntakeStatus,
    InvestigationStatus,
    ReviewItemType,
    ReviewStatus,
    SubjectType,
)
from found_core.domain.investigation import CACHEABLE_STATUSES
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
from found_core.ports.budget import BudgetUsage
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
        self.incident_records: dict[str, Incident] = {}
        self.activity: list[Activity] = []
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
        self.locations: dict[str, Location] = {}
        self.settings = Settings()
        self.investigations: dict[str, Investigation] = {}
        self.run_locks: dict[str, tuple[str, datetime]] = {}
        self.steps: dict[tuple[str, int], InvestigationStep] = {}
        self.identity_proposals: dict[str, IdentityProposal] = {}
        self.identity_decisions: dict[str, IdentityDecision] = {}
        self.intake_jobs: dict[str, IntakeJob] = {}
        self.intake_candidates: dict[str, IntakeCandidate] = {}

    def add_incident(self, incident_id: str) -> None:
        self.incidents.add(incident_id)

    def get_incident(self, incident_id: str) -> Incident | None:
        if incident_id not in self.incidents:
            return None
        return self.incident_records.get(incident_id) or Incident(id=incident_id, name=incident_id)

    def put_incident(self, incident: Incident) -> None:
        self.incidents.add(incident.id)
        self.incident_records[incident.id] = incident

    def put_organization(self, org: Organization) -> None:
        self.add_organization(org)

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

    def ensure_location(self, location: Location) -> Location:
        with self._lock:
            return self.locations.setdefault(location.id, location)

    def list_locations(self, incident_id: str) -> list[Location]:
        return [loc for loc in self.locations.values() if loc.incident_id == incident_id]

    def list_incident_claims(self, incident_id: str) -> list[Claim]:
        found = [c for c in self.claims.values() if c.incident_id == incident_id]
        return sorted(found, key=lambda c: (c.ingested_at, c.id))

    def get_review_item(self, incident_id: str, review_id: str) -> ReviewItem | None:
        item = self.review_items.get(review_id)
        return item if item and item.incident_id == incident_id else None

    def list_source_claims(
        self, source_id: str, limit: int, subject_id: str | None = None
    ) -> list[Claim]:
        found = [
            c
            for c in self.claims.values()
            if c.source_id == source_id and (subject_id is None or c.subject_id == subject_id)
        ]
        return sorted(found, key=_feed_key, reverse=True)[:limit]

    def count_tool_call(self, investigation_id: str, cap: int) -> int | None:
        with self._lock:
            current = self.investigations.get(investigation_id)
            if (
                current is None
                or current.status != InvestigationStatus.RUNNING
                or current.tool_calls >= cap
            ):
                return None
            count = current.tool_calls + 1
            self.investigations[investigation_id] = current.model_copy(
                update={"tool_calls": count}
            )
            return count

    def latest_source_claim_id(self, source_id: str) -> str | None:
        found = self.list_source_claims(source_id, 1)
        return found[0].id if found else None

    def get_settings(self) -> Settings:
        return self.settings

    def put_investigation(self, investigation: Investigation) -> None:
        with self._lock:
            if investigation.id in self.investigations:
                raise ValueError("investigation id already exists")
            self.investigations[investigation.id] = investigation

    def get_investigation(self, investigation_id: str) -> Investigation | None:
        return self.investigations.get(investigation_id)

    def update_investigation_if(
        self,
        investigation_id: str,
        expected_status: InvestigationStatus,
        changes: dict[str, Any],
    ) -> Investigation | None:
        with self._lock:
            current = self.investigations.get(investigation_id)
            if current is None or current.status != expected_status:
                return None
            updated = Investigation.model_validate({**current.model_dump(), **changes})
            if updated.id != investigation_id:
                raise ValueError("an update cannot change the id")
            if updated.status in CACHEABLE_STATUSES and updated.finished_at is None:
                raise ValueError("a cacheable result needs finished_at")
            self.investigations[investigation_id] = updated
            return updated

    def find_cached_investigation(self, fingerprint: str) -> Investigation | None:
        found = [
            i
            for i in self.investigations.values()
            if i.fingerprint == fingerprint and i.status in CACHEABLE_STATUSES
        ]
        return max(found, key=lambda i: i.finished_at or i.queued_at) if found else None

    def acquire_run_lock(
        self, claim_id: str, investigation_id: str, now: datetime, expires_at: datetime
    ) -> str:
        with self._lock:
            held = self.run_locks.get(claim_id)
            if held is not None and held[1] > now:
                return held[0]
            self.run_locks[claim_id] = (investigation_id, expires_at)
            return investigation_id

    def release_run_lock(self, claim_id: str, investigation_id: str) -> None:
        with self._lock:
            held = self.run_locks.get(claim_id)
            if held is not None and held[0] == investigation_id:
                del self.run_locks[claim_id]

    def put_investigation_step(self, step: InvestigationStep) -> bool:
        key = (step.investigation_id, step.seq)
        with self._lock:
            if key in self.steps:
                return False
            self.steps[key] = step
            return True

    def list_review_items(
        self,
        incident_id: str,
        status: ReviewStatus,
        limit: int,
        item_type: ReviewItemType | None = None,
        after: dict[str, str] | None = None,
    ) -> tuple[list[ReviewItem], dict[str, str] | None]:
        found = sorted(
            (
                i
                for i in self.review_items.values()
                if i.incident_id == incident_id
                and i.status == status
                and (item_type is None or i.item_type == item_type)
            ),
            key=_queue_key,
        )
        if after is not None:
            if set(after) != {"s", "r"}:
                raise ValueError("position does not belong to this listing")
            found = [i for i in found if _queue_key(i) > after["s"]]
        page = found[:limit]
        if len(found) <= limit:
            return page, None
        return page, {"s": _queue_key(page[-1]), "r": page[-1].id}

    def resolve_review_item(
        self, incident_id: str, review_id: str, resolved_by: str, note: str | None, at: datetime
    ) -> ReviewItem | None:
        with self._lock:
            item = self.review_items.get(review_id)
            if item is None or item.incident_id != incident_id or item.status != ReviewStatus.OPEN:
                return None
            done = item.model_copy(
                update={
                    "status": ReviewStatus.DONE,
                    "resolved_by": resolved_by,
                    "resolved_at": at,
                    "note": note,
                }
            )
            self.review_items[review_id] = done
            return done

    def get_alert(self, subscription_id: str, claim_id: str) -> Alert | None:
        return self.alerts.get((subscription_id, claim_id))

    def release_held_alert(
        self, subscription_id: str, claim_id: str, status: DeliveryStatus
    ) -> bool:
        with self._lock:
            alert = self.alerts.get((subscription_id, claim_id))
            if alert is None or alert.delivery_status != DeliveryStatus.HELD:
                return False
            self.alerts[(subscription_id, claim_id)] = alert.model_copy(
                update={"delivery_status": status}
            )
            return True

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
        with self._lock:
            alert = self.alerts.get((subscription_id, claim_id))
            if alert is None or alert.delivery_status != expected:
                return False
            changes: dict[str, Any] = {"delivery_status": status}
            if channels:
                changes["delivered_channels"] = channels
            if note is not None:
                changes["delivery_note"] = note
            if at is not None:
                changes["delivered_at"] = at
            self.alerts[(subscription_id, claim_id)] = alert.model_copy(update=changes)
            return True

    def put_intake_job(self, job: IntakeJob) -> None:
        with self._lock:
            if job.id in self.intake_jobs:
                raise ValueError("intake job id already exists")
            self.intake_jobs[job.id] = job

    def get_intake_job(self, job_id: str) -> IntakeJob | None:
        return self.intake_jobs.get(job_id)

    def update_intake_job_if(
        self, job_id: str, expected: tuple[IntakeStatus, ...], changes: dict[str, Any]
    ) -> IntakeJob | None:
        with self._lock:
            job = self.intake_jobs.get(job_id)
            if job is None or job.status not in expected:
                return None
            updated = IntakeJob.model_validate({**job.model_dump(), **changes})
            self.intake_jobs[job_id] = updated
            return updated

    def put_intake_candidates(self, candidates: list[IntakeCandidate]) -> None:
        with self._lock:
            for c in candidates:
                taken = any(
                    o.job_id == c.job_id and o.idx == c.idx for o in self.intake_candidates.values()
                )
                if not taken:
                    self.intake_candidates[c.id] = c

    def list_intake_candidates(self, job_id: str) -> list[IntakeCandidate]:
        return sorted(
            (c for c in self.intake_candidates.values() if c.job_id == job_id),
            key=lambda c: c.idx,
        )

    def get_intake_candidate(self, candidate_id: str) -> IntakeCandidate | None:
        return self.intake_candidates.get(candidate_id)

    def save_candidate_decision(self, candidate: IntakeCandidate) -> bool:
        with self._lock:
            current = self.intake_candidates.get(candidate.id)
            if current is None or current.status != CandidateStatus.PENDING_REVIEW:
                return False
            self.intake_candidates[candidate.id] = candidate
            return True

    def put_identity_proposal_if_absent(self, proposal: IdentityProposal) -> bool:
        with self._lock:
            if proposal.pair_key in self.identity_proposals:
                return False
            self.identity_proposals[proposal.pair_key] = proposal
            return True

    def get_identity_proposal(self, incident_id: str, pair_key: str) -> IdentityProposal | None:
        proposal = self.identity_proposals.get(pair_key)
        return proposal if proposal and proposal.incident_id == incident_id else None

    def get_identity_decision(self, incident_id: str, pair_key: str) -> IdentityDecision | None:
        decision = self.identity_decisions.get(pair_key)
        return decision if decision and decision.incident_id == incident_id else None

    def save_identity_decision(self, decision: IdentityDecision, expected_version: int) -> bool:
        with self._lock:
            current = self.identity_decisions.get(decision.pair_key)
            if (current.version if current else 0) != expected_version:
                return False
            self.identity_decisions[decision.pair_key] = decision
            return True

    def list_identity_decisions(self, incident_id: str, person_id: str) -> list[IdentityDecision]:
        return sorted(
            (
                d
                for d in self.identity_decisions.values()
                if d.incident_id == incident_id and person_id in (d.person_a_id, d.person_b_id)
            ),
            key=lambda d: d.pair_key,
        )

    def put_activity(self, activity: Activity) -> None:
        self.activity.append(activity)

    def list_activity(self, incident_id: str, limit: int) -> list[Activity]:
        found = [a for a in self.activity if a.incident_id == incident_id]
        return sorted(found, key=lambda a: (a.created_at, a.id), reverse=True)[:limit]

    def delete_incident_data(self, incident_id: str) -> int:
        with self._lock:
            subjects = {s for s, v in self.subjects.items() if v.incident_id == incident_id}
            claims = {c for c, v in self.claims.items() if v.incident_id == incident_id}
            investigations = {
                i for i, v in self.investigations.items() if v.incident_id == incident_id
            }
            removed = 0

            def drop(store: dict, keys) -> int:
                keys = list(keys)
                for key in keys:
                    del store[key]
                return len(keys)

            removed += drop(self.subjects, subjects)
            removed += drop(self.claims, claims)
            removed += drop(self.investigations, investigations)
            removed += drop(
                self.steps, [k for k, v in self.steps.items() if v.incident_id == incident_id]
            )
            removed += drop(
                self.sources, [k for k, v in self.sources.items() if v.incident_id == incident_id]
            )
            removed += drop(
                self.locations,
                [k for k, v in self.locations.items() if v.incident_id == incident_id],
            )
            removed += drop(
                self.organizations, [k for k in self.organizations if k[0] == incident_id]
            )
            removed += drop(
                self.markers, [k for k, v in self.markers.items() if v.claim_id in claims]
            )
            removed += drop(
                self.subscriptions,
                [k for k, v in self.subscriptions.items() if v.subject_id in subjects],
            )
            removed += drop(
                self.alerts, [k for k, v in self.alerts.items() if v.incident_id == incident_id]
            )
            removed += drop(
                self.review_items,
                [k for k, v in self.review_items.items() if v.incident_id == incident_id],
            )
            removed += drop(self.run_locks, [k for k in self.run_locks if k in claims])
            for store in (
                self.identity_proposals,
                self.identity_decisions,
                self.intake_jobs,
                self.intake_candidates,
            ):
                removed += drop(
                    store, [k for k, v in store.items() if v.incident_id == incident_id]
                )
            for token in list(self.name_tokens):
                self.name_tokens[token] -= subjects
                if not self.name_tokens[token]:
                    del self.name_tokens[token]
            kept = [a for a in self.activity if a.incident_id != incident_id]
            removed += len(self.activity) - len(kept)
            self.activity = kept
            self.incidents.discard(incident_id)
            self.incident_records.pop(incident_id, None)
            return removed + 1

    def list_investigation_steps(self, investigation_id: str) -> list[InvestigationStep]:
        found = [s for (inv, _), s in self.steps.items() if inv == investigation_id]
        return sorted(found, key=lambda s: s.seq)


def _queue_key(item: ReviewItem) -> str:
    """Same order as the review queue index: priority, then creation time, then id."""
    created = item.model_dump(mode="json")["created_at"]
    return f"{item.priority}#{created}#{item.id}"


def _feed_key(claim: Claim) -> str:
    """Same order as the source feed index: reported time as stored, then claim id."""
    reported = claim.model_dump(mode="json")["reported_at"] or "0"
    return f"{reported}#{claim.id}"


class InMemoryBudgetLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.periods: dict[str, BudgetUsage] = {}

    def _bump(self, period: str, field: str, cap: int) -> bool:
        with self._lock:
            usage = self.periods.get(period, BudgetUsage(period))
            if getattr(usage, field) >= cap:
                return False
            self.periods[period] = replace(usage, **{field: getattr(usage, field) + 1})
            return True

    def reserve_run(self, period: str, cap: int) -> bool:
        return self._bump(period, "runs", cap)

    def count_model_call(self, period: str, cap: int) -> bool:
        return self._bump(period, "model_calls", cap)

    def add_tokens(self, period: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            usage = self.periods.get(period, BudgetUsage(period))
            self.periods[period] = replace(
                usage,
                input_tokens=usage.input_tokens + input_tokens,
                output_tokens=usage.output_tokens + output_tokens,
            )

    def usage(self, period: str) -> BudgetUsage:
        return self.periods.get(period, BudgetUsage(period))
