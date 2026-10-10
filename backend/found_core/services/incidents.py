"""The incident itself and its newest reports, for the incident overview page.

Recent reports follow the same visibility rules as timelines (product rule 8): a
sensitive report a reviewer has not released reaches other roles only as a notice.
"""

from dataclasses import dataclass

from found_core.domain.auth import Caller
from found_core.domain.enums import ReviewItemType, ReviewStatus
from found_core.domain.errors import NotFound
from found_core.domain.ids import review_item_id
from found_core.domain.models import Claim, Incident, Subject
from found_core.domain.visibility import is_sensitive, sees_sensitive
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read

RECENT_MAX = 20


@dataclass(frozen=True)
class RecentReport:
    claim: Claim
    subject: Subject | None
    source_name: str
    withheld: bool = False


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
        self, caller: Caller, incident_id: str, limit: int = 10
    ) -> list[RecentReport]:
        """The incident's newest reports by arrival, at most RECENT_MAX."""
        self.details(caller, incident_id)
        claims = sorted(
            self._repo.list_incident_claims(incident_id),
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

    def _withheld(self, caller: Caller, claim: Claim) -> bool:
        if sees_sensitive(caller) or not is_sensitive(claim):
            return False
        item = self._repo.get_review_item(
            claim.incident_id, review_item_id(ReviewItemType.HELD_ALERT, claim.id)
        )
        return item is None or item.status != ReviewStatus.DONE
