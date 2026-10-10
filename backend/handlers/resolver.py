"""Rule target for inserted person records. Converts the event and calls the resolver.

Errors are raised so Lambda retries the event and then sends it to the dead-letter
queue. Retrying is safe because proposals and review items are put-if-absent.
"""

from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.domain.enums import SubjectType
from found_core.events import NotADomainEvent, SubjectCreated, from_bus_event

logger = Logger(service="resolver")


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        domain_event = from_bus_event(event)
    except NotADomainEvent:
        # A routing mistake, not a transient failure: retrying cannot help.
        logger.error("event is not from the table stream", extra={"event_id": event.get("id")})
        return {"status": "ignored"}
    if (
        not isinstance(domain_event, SubjectCreated)
        or domain_event.subject_type != SubjectType.PERSON
    ):
        logger.warning("not a person event", extra={"event_id": event.get("id")})
        return {"status": "ignored"}

    logger.append_keys(incident_id=domain_event.incident_id, person_id=domain_event.subject_id)
    result = container.resolve_service().on_person_created(domain_event.subject_id)
    summary = {
        "status": "skipped" if result.skipped_reason else "resolved",
        "candidates": result.candidates,
        "proposals_created": result.proposals_created,
        "skipped_reason": result.skipped_reason,
    }
    logger.info("person resolved", extra=summary)
    return summary
