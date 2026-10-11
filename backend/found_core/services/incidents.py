"""The incident itself, its newest reports and who published them.

Recent reports follow the same visibility rules as timelines (product rule 8): a
sensitive report a reviewer has not released reaches other roles only as a notice.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from found_core.domain.auth import Caller
from found_core.domain.enums import ReviewItemType, ReviewStatus
from found_core.domain.errors import NotFound
from found_core.domain.ids import review_item_id
from found_core.domain.models import Claim, Incident, Source, Subject
from found_core.domain.visibility import is_sensitive, sees_sensitive
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read

RECENT_MAX = 20
# Counted under this key instead of their type while a reviewer holds them.
WITHHELD_KEY = "WITHHELD"


@dataclass(frozen=True)
class RecentReport:
    claim: Claim
    subject: Subject | None
    source_name: str
    withheld: bool = False


@dataclass(frozen=True)
class SourceSummary:
    """One publisher in an incident: how many reports it made and how often others cite it."""

    source: Source
    reports: int
    by_type: dict[str, int] = field(default_factory=dict)
    cited_by: int = 0
    latest_at: datetime | None = None


class IncidentService:
    def __init__(self, repo: FoundRepository) -> None:
        self._repo = repo

    def details(self, caller: Caller, incident_id: str) -> Incident:
        incident = self._repo.get_incident(incident_id)
        if incident is None:
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)
        return incident

    def recent_reports(
        self, caller: Caller, incident_id: str, limit: int = 10, source_id: str | None = None
    ) -> list[RecentReport]:
        """The newest reports by arrival, at most RECENT_MAX, from one source if given."""
        self.details(caller, incident_id)
        claims = sorted(
            (
                c
                for c in self._repo.list_incident_claims(incident_id)
                if source_id is None or c.source_id == source_id
            ),
            key=lambda c: (c.ingested_at, c.id),
            reverse=True,
        )[: max(1, min(limit, RECENT_MAX))]
        subjects = {s.id: s for s in self._repo.get_subjects([c.subject_id for c in claims])}
        sources = {s.id: s.name for s in self._repo.list_sources(incident_id)}
        return [
            RecentReport(
                claim=c,
                subject=subjects.get(c.subject_id),
                source_name=sources.get(c.source_id, c.source_id),
                withheld=self._withheld(caller, c),
            )
            for c in claims
        ]

    def sources(self, caller: Caller, incident_id: str) -> list[SourceSummary]:
        """Every source in the incident, busiest first.

        cited_by counts reports from other sources that name this one: relays, which
        are never independent confirmation (product rule 5).
        """
        self.details(caller, incident_id)
        claims = self._repo.list_incident_claims(incident_id)
        by_type: dict[str, Counter[str]] = {}
        latest: dict[str, datetime] = {}
        cited: Counter[str] = Counter()
        for claim in claims:
            key = WITHHELD_KEY if self._withheld(caller, claim) else claim.claim_type
            by_type.setdefault(claim.source_id, Counter())[key] += 1
            if claim.source_id not in latest or claim.ingested_at > latest[claim.source_id]:
                latest[claim.source_id] = claim.ingested_at
            for mentioned in set(claim.mentioned_source_ids) - {claim.source_id}:
                cited[mentioned] += 1
        summaries = [
            SourceSummary(
                source=source,
                reports=sum(by_type.get(source.id, Counter()).values()),
                by_type=dict(by_type.get(source.id, Counter())),
                cited_by=cited[source.id],
                latest_at=latest.get(source.id),
            )
            for source in self._repo.list_sources(incident_id)
        ]
        return sorted(summaries, key=lambda s: (-s.reports, s.source.name_norm, s.source.id))

    def _withheld(self, caller: Caller, claim: Claim) -> bool:
        if sees_sensitive(caller) or not is_sensitive(claim):
            return False
        item = self._repo.get_review_item(
            claim.incident_id, review_item_id(ReviewItemType.HELD_ALERT, claim.id)
        )
        return item is None or item.status != ReviewStatus.DONE
