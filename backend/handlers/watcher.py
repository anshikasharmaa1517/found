"""Rule target for inserted claims. Converts the event and calls the watch service.

Errors are raised so Lambda retries the event and then sends it to the dead-letter
queue. Retrying is safe because every write in the service is put-if-absent.
"""

from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.events import ClaimCreated, NotADomainEvent, from_bus_event

logger = Logger(service="watcher")


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        domain_event = from_bus_event(event)
    except NotADomainEvent:
        # A routing mistake, not a transient failure: retrying cannot help.
        logger.error("event is not from the table stream", extra={"event_id": event.get("id")})
        return {"status": "ignored"}
    if not isinstance(domain_event, ClaimCreated):
        logger.warning("not a claim event", extra={"event_id": event.get("id")})
        return {"status": "ignored"}

    logger.append_keys(
        incident_id=domain_event.incident_id,
        subject_id=domain_event.subject_id,
        claim_id=domain_event.claim_id,
    )
    result = container.watch_service().on_claim_created(
        domain_event.subject_id, domain_event.claim_id, domain_event.seq
    )
    summary = {
        "status": "skipped" if result.skipped_reason else "watched",
        "relation": result.relation.value if result.relation else None,
        "alerts_created": result.alerts_created,
        "review_items_created": [t.value for t in result.review_items_created],
        "skipped_reason": result.skipped_reason,
    }
    logger.info("claim watched", extra=summary)
    return summary
