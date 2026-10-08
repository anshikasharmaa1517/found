"""Publishing a report on behalf of a signed-in publisher (design Sections 5.1 and 7.3)."""

from dataclasses import dataclass
from typing import Any

from found_core.domain.auth import PUBLISHER, Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.errors import Forbidden, NotFound, ValidationFailed
from found_core.domain.models import Claim, Organization
from found_core.ports.repository import FoundRepository
from found_core.services.ingest import IngestService

# Set from the verified identity only. A body that carries them is rejected, not overwritten.
IDENTITY_FIELDS = frozenset({"org_id", "org_name", "org_type", "actor", "extraction_method"})


@dataclass(frozen=True)
class PublishedReport:
    claim: Claim
    replayed: bool
    publisher: Organization


class ReportService:
    def __init__(self, repo: FoundRepository, ingest: IngestService) -> None:
        self._repo = repo
        self._ingest = ingest

    def publish(self, caller: Caller, incident_id: str, body: dict[str, Any]) -> PublishedReport:
        if not caller.has(PUBLISHER) or not caller.org_id:
            raise Forbidden("Only publishers can submit reports.")
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        org = self._repo.get_organization(incident_id, caller.org_id)
        if org is None:
            raise Forbidden("Your organization is not registered for this incident.")

        sent = sorted(IDENTITY_FIELDS & body.keys())
        if sent:
            raise ValidationFailed(
                "Report is invalid.",
                errors=[
                    {"field": f, "message": "Set from your sign-in, not the request."}
                    for f in sent
                ],
            )

        cmd = PublishCommand.parse(
            {
                **body,
                "incident_id": incident_id,
                "org_id": org.id,
                "org_name": org.name,
                "org_type": org.org_type,
                "actor": caller.user_id,
            }
        )
        result = self._ingest.publish(cmd)
        return PublishedReport(claim=result.claim, replayed=result.replayed, publisher=org)
