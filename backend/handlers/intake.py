"""The intake workflow's steps (design Section 5.3). One function, one step per call.

The state machine passes `step` and that step's input. An `ExtractionFailed` ends the
job with its reason; anything else is raised so the workflow can retry it and, if it
still fails, the `fail` step records the error type as the reason.
"""

import json
from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.domain.intake import parse_intake_key

logger = Logger(service="intake")


def _reason(error: dict[str, Any] | None) -> str:
    """The reason to record from a Step Functions catch: our reason, or the error type."""
    if not error:
        return "UNKNOWN"
    kind = str(error.get("Error", "UNKNOWN"))
    try:
        cause = json.loads(error.get("Cause") or "{}")
    except ValueError:
        cause = {}
    if kind == "ExtractionFailed" and cause.get("errorMessage"):
        return str(cause["errorMessage"])
    return kind


def _job_from_key(key: str | None) -> str | None:
    try:
        return parse_intake_key(key or "")[1]
    except ValueError:
        return None


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    step = event.get("step")
    service = container.intake_service()
    match step:
        case "validate":
            result = service.validate_object(str(event["key"]))
        case "extract":
            result = service.extract(str(event["job_id"]))
            logger.info(
                "candidates extracted",
                extra={
                    "job_id": event["job_id"],
                    "kept": len(result["candidates"]),
                    "dropped": result["dropped"],
                },
            )
        case "store":
            result = service.store(str(event["job_id"]), list(event.get("candidates") or []))
        case "fail":
            reason = _reason(event.get("error"))
            result = service.mark_failed(_job_from_key(event.get("key")), reason)
            logger.warning("intake failed", extra={"key": event.get("key"), "reason": reason})
        case _:
            raise ValueError(f"unknown intake step {step!r}")
    return result
