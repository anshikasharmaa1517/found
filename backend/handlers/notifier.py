"""Rule target for due alerts: new PENDING alerts and released held alerts.

Errors are raised so Lambda retries the event and then sends it to the dead-letter
queue. A retry never sends twice: the service claims each alert before sending.
"""

from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.domain.enums import DeliveryStatus
from found_core.events import AlertCreated, AlertReleased, NotADomainEvent, from_bus_event

logger = Logger(service="notifier")


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        domain_event = from_bus_event(event)
    except NotADomainEvent:
        # A routing mistake, not a transient failure: retrying cannot help.
        logger.error("event is not from the table stream", extra={"event_id": event.get("id")})
        return {"status": "ignored"}
    due = isinstance(domain_event, AlertReleased) or (
        isinstance(domain_event, AlertCreated)
        and domain_event.delivery_status == DeliveryStatus.PENDING
    )
    if not due:
        logger.warning("not a due alert", extra={"event_id": event.get("id")})
        return {"status": "ignored"}

    logger.append_keys(
        incident_id=domain_event.incident_id,
        alert_id=domain_event.alert_id,
        claim_id=domain_event.claim_id,
    )
    result = container.notify_service().deliver(domain_event.subscription_id, domain_event.claim_id)
    # Never log addresses or numbers; the channel names and status are enough.
    summary = {
        "status": result.status.value if result.status else "skipped",
        "sent": result.sent,
        "note": result.note,
        "skipped_reason": result.skipped_reason,
    }
    logger.info("alert delivery", extra=summary)
    return summary
