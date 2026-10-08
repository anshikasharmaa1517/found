"""Who gets which live message, and what it says (design Sections 5.4, 6.5 and 7.5).

Pure rules over domain events, kept beside `found_core.events` rather than in `domain/`
because they depend on the event contract.

Messages are notifications only: ids and short text. Clients refetch anything else,
so a missed or repeated message never leaves the screen wrong for long.
"""

from typing import Any

from found_core.domain.auth import ADMIN, PUBLISHER, REVIEWER
from found_core.domain.models import Connection
from found_core.events import (
    AlertCreated,
    ClaimCreated,
    DomainEvent,
    InvestigationStepCreated,
    InvestigationUpdated,
    ReviewCreated,
)

MAX_CONNECTIONS_PER_USER = 3
CONNECTION_HOURS = 2  # API Gateway closes WebSocket connections after two hours anyway.

_INCIDENT_FEED = frozenset({PUBLISHER, REVIEWER, ADMIN})
_REVIEW_FEED = frozenset({REVIEWER, ADMIN})


def _iso(event: DomainEvent) -> str:
    return event.model_dump(mode="json")["occurred_at"]


def message_for(event: DomainEvent) -> dict[str, Any] | None:
    match event:
        case ClaimCreated():
            return {
                "type": "claim.created",
                "incident_id": event.incident_id,
                "claim_id": event.claim_id,
                "subject_id": event.subject_id,
                "at": _iso(event),
            }
        case AlertCreated():
            return {
                "type": "alert.created",
                "alert_id": event.alert_id,
                "subject_id": event.subject_id,
                "severity": event.severity.value,
                "message": event.message,
            }
        case ReviewCreated():
            return {
                "type": "review.created",
                "incident_id": event.incident_id,
                "review_id": event.review_id,
                "item_type": event.item_type.value,
            }
        case InvestigationStepCreated():
            return {
                "type": "investigation.step",
                "incident_id": event.incident_id,
                "investigation_id": event.investigation_id,
                "seq": event.seq,
                "kind": event.kind.value,
                "tool": event.tool_name,
                "summary": event.summary,
            }
        case InvestigationUpdated():
            return {
                "type": "investigation.updated",
                "incident_id": event.incident_id,
                "investigation_id": event.investigation_id,
                "claim_id": event.claim_id,
                "status": event.status.value,
            }
    return None


def receives(connection: Connection, event: DomainEvent) -> bool:
    """Family accounts only ever get their own alerts; staff get their incident's feed."""
    groups = set(connection.groups)
    match event:
        case AlertCreated():
            return connection.user_id == event.user_id
        case ClaimCreated():
            return connection.incident_id == event.incident_id and bool(groups & _INCIDENT_FEED)
        case ReviewCreated() | InvestigationStepCreated() | InvestigationUpdated():
            # Investigations are reviewer work: publishers do not see the trace.
            return connection.incident_id == event.incident_id and bool(groups & _REVIEW_FEED)
    return False
