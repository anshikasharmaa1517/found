"""Reset worker: removes the demo incident's items and reloads it (design Section 5.5).

Invoked asynchronously by the API after it checked the caller. Errors raise, so Lambda
retries; a reset can run again safely because the load is idempotent by reference.
"""

from dataclasses import asdict
from typing import Any

from aws_lambda_powertools import Logger

from found_core import container

logger = Logger(service="demo_reset")


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    incident_id = str(event.get("incident_id") or "")
    actor = str(event.get("actor") or "unknown")
    logger.append_keys(incident_id=incident_id, actor=actor)
    result = container.demo_service().reset(incident_id, actor)
    logger.info("demo reset", extra=asdict(result))
    return asdict(result)
