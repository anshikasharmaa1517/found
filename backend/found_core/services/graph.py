"""The incident graph: every stored record and the typed links between them."""

from found_core.domain.auth import Caller
from found_core.domain.enums import ReviewItemType, ReviewStatus, SubjectType
from found_core.domain.errors import NotFound
from found_core.domain.graph import Graph, build_graph
from found_core.domain.ids import review_item_id
from found_core.domain.models import Claim, Subject
from found_core.domain.visibility import is_sensitive, sees_sensitive
from found_core.ports.repository import FoundRepository, NamePosition
from found_core.services.access import ensure_can_read

# Subjects read per type; a district-sized incident, not a census.
SUBJECTS_MAX = 1000


class GraphService:
    def __init__(self, repo: FoundRepository) -> None:
        self._repo = repo

    def graph(self, caller: Caller, incident_id: str) -> Graph:
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)
        reviewer = sees_sensitive(caller)
        claims = self._repo.list_incident_claims(incident_id)
        proposals, decisions = self._repo.list_incident_identity(incident_id)
        return build_graph(
            subjects=self._subjects(incident_id),
            claims=claims,
            sources=self._repo.list_sources(incident_id),
            locations=self._repo.list_locations(incident_id),
            investigations=self._repo.list_incident_investigations(incident_id) if reviewer else (),
            proposals=proposals,
            decisions=decisions,
            withheld=set() if reviewer else self._withheld(claims),
            reviewer=reviewer,
        )

    def _subjects(self, incident_id: str) -> list[Subject]:
        found: list[Subject] = []
        for subject_type in SubjectType:
            after: NamePosition | None = None
            count = 0
            while count < SUBJECTS_MAX:
                batch = self._repo.list_subjects(incident_id, subject_type, 200, after)
                found += batch
                count += len(batch)
                if len(batch) < 200:
                    break
                after = NamePosition(name_norm=batch[-1].name_norm, subject_id=batch[-1].id)
        return found

    def _withheld(self, claims: list[Claim]) -> set[str]:
        """Sensitive reports not yet released by a reviewer (product rule 8)."""
        hidden: set[str] = set()
        for claim in claims:
            if not is_sensitive(claim):
                continue
            item = self._repo.get_review_item(
                claim.incident_id, review_item_id(ReviewItemType.HELD_ALERT, claim.id)
            )
            if item is None or item.status != ReviewStatus.DONE:
                hidden.add(claim.id)
        return hidden
