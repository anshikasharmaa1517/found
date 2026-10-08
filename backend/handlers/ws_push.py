"""Rule target for inserted claims, alerts and review items: push a short notice."""

from dataclasses import asdict
from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.events import NotADomainEvent, from_bus_event

logger = Logger(service="ws_push")


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        domain_event = from_bus_event(event)
    except NotADomainEvent:
        logger.error("event is not from the table stream", extra={"event_id": event.get("id")})
        return {"status": "ignored"}
    if domain_event is None:
        return {"status": "ignored"}
    logger.append_keys(incident_id=domain_event.incident_id, event_type=domain_event.type)
    result = asdict(container.push_service().push(domain_event))
    logger.info("pushed", extra=result)
    return {"status": "pushed", **result}
