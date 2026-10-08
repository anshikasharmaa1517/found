"""SQS target for the run queue. One message names one investigation.

Batch size is 1. Agent problems end as a FAILED run with a reason, not as an error, so
only infrastructure failures make SQS deliver again. On the last delivery attempt the
run is failed before the message moves to the dead-letter queue, so no run stays QUEUED.
"""

import json
from typing import Any

from aws_lambda_powertools import Logger

from found_core import container

logger = Logger(service="investigation_runner")

MAX_RECEIVES = 2


def _investigation_id(record: dict[str, Any]) -> str | None:
    try:
        body = json.loads(record.get("body") or "")
    except ValueError:
        return None
    value = body.get("investigation_id") if isinstance(body, dict) else None
    return value if isinstance(value, str) and value else None


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        message_id = record.get("messageId", "")
        investigation_id = _investigation_id(record)
        if investigation_id is None:
            # Retrying cannot fix a malformed body.
            logger.error("message has no investigation id", extra={"message_id": message_id})
            continue
        logger.append_keys(investigation_id=investigation_id)
        runner = container.investigation_runner()
        try:
            result = runner.run(investigation_id)
        except Exception:
            receives = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
            logger.exception("run failed", extra={"receive_count": receives})
            if receives >= MAX_RECEIVES:
                runner.fail_queued(investigation_id, "RUNNER_ERROR")
            failures.append({"itemIdentifier": message_id})
            continue
        logger.info(
            "run finished",
            extra={
                "status": result.status.value if result.status else None,
                "steps": result.steps,
                "skipped_reason": result.skipped_reason,
                "failure_reason": result.failure_reason,
            },
        )
    return {"batchItemFailures": failures}
