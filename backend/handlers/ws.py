"""WebSocket routes: connect, disconnect, subscribe, and anything else."""

import json
from typing import Any

from aws_lambda_powertools import Logger

from found_core import container
from found_core.domain.auth import Caller
from found_core.domain.errors import FoundError, Unauthenticated

logger = Logger(service="ws")


def _reply(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {"statusCode": status, "body": json.dumps(body, ensure_ascii=False)}


def _error(err: FoundError) -> dict[str, Any]:
    return _reply(
        err.http_status,
        {"type": "error", "error": {"code": err.code, "message": err.message}},
    )


def _connect_caller(request_context: dict[str, Any]) -> Caller:
    auth = request_context.get("authorizer") or {}
    return Caller.from_claims(
        {
            "sub": auth.get("user_id"),
            "cognito:groups": auth.get("groups", ""),
            "custom:org_id": auth.get("org_id") or None,
        }
    )


def _body(event: dict[str, Any]) -> dict[str, Any]:
    try:
        body = json.loads(event.get("body") or "")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_context = event["requestContext"]
    route = request_context["routeKey"]
    connection_id = request_context["connectionId"]
    logger.append_keys(connection_id=connection_id, route=route)
    service = container.connection_service()

    if route == "$connect":
        try:
            caller = _connect_caller(request_context)
        except Unauthenticated:
            return {"statusCode": 401}
        service.connect(caller, connection_id)
        return {"statusCode": 200}
    if route == "$disconnect":
        service.disconnect(connection_id)
        return {"statusCode": 200}
    if route == "subscribe":
        try:
            incident_id = service.subscribe(connection_id, _body(event))
        except FoundError as err:
            return _error(err)
        return _reply(200, {"type": "subscribed", "incident_id": incident_id})
    return _reply(
        400,
        {"type": "error", "error": {"code": "BAD_REQUEST", "message": "Unknown action."}},
    )
