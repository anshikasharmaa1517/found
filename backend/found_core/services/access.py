"""Who may read an incident's data (design Section 7.1)."""

from found_core.domain.auth import ADMIN, FAMILY, PUBLISHER, REVIEWER, Caller
from found_core.domain.errors import Forbidden
from found_core.ports.repository import FoundRepository

_READ_ANY_INCIDENT = (ADMIN, REVIEWER, FAMILY)


def ensure_can_read(repo: FoundRepository, caller: Caller, incident_id: str) -> None:
    """Reviewers, families and admins read every incident; publishers only their own."""
    if any(caller.has(group) for group in _READ_ANY_INCIDENT):
        return
    if (
        caller.has(PUBLISHER)
        and caller.org_id
        and repo.get_organization(incident_id, caller.org_id) is not None
    ):
        return
    raise Forbidden("You do not have access to this incident.")
