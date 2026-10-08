"""HTTP API entry point. Parses the request, calls a service and maps errors to responses."""

import json
from http import HTTPStatus
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.logging import correlation_paths

from found_core import container
from found_core.domain.auth import Caller
from found_core.domain.errors import BadRequest, FoundError
from found_core.domain.models import Claim

logger = Logger(service="api")
app = APIGatewayHttpResolver()


def _request_id() -> str:
    return app.current_event.request_context.request_id or ""


def _json(status: int, body: dict[str, Any]) -> Response:
    return Response(
        status_code=status,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False),
        headers={"x-request-id": _request_id()},
    )


def _caller() -> Caller:
    authorizer = app.current_event.request_context.authorizer
    claims = authorizer.jwt_claim if authorizer else None
    return Caller.from_claims(claims)


def _body() -> dict[str, Any]:
    try:
        body = json.loads(app.current_event.body or "")
    except (TypeError, ValueError):
        raise BadRequest("Body must be JSON.") from None
    if not isinstance(body, dict):
        raise BadRequest("Body must be a JSON object.")
    return body


def claim_view(claim: Claim, source_name: str, source_type: str) -> dict[str, Any]:
    data = claim.model_dump(mode="json")
    return {
        "id": data["id"],
        "incident_id": data["incident_id"],
        "subject_id": data["subject_id"],
        "source": {"id": data["source_id"], "name": source_name, "type": source_type},
        "seq": data["seq"],
        "claim_type": data["claim_type"],
        "value": data["value"],
        "reported_at": data["reported_at"],
        "reported_at_raw": data["reported_at_raw"],
        "ingested_at": data["ingested_at"],
        "extraction_method": data["extraction_method"],
        "mentioned_source_ids": data["mentioned_source_ids"],
        "payload_hash": data["payload_hash"],
    }


@app.get("/v1/health")
def health() -> Response:
    return _json(HTTPStatus.OK, {"status": "ok"})


@app.post("/v1/incidents/<incident_id>/reports")
def publish_report(incident_id: str) -> Response:
    caller = _caller()
    body = _body()
    result = container.report_service().publish(caller, incident_id, body)
    view = claim_view(result.claim, result.publisher.name, result.publisher.org_type.value)
    status = HTTPStatus.OK if result.replayed else HTTPStatus.CREATED
    return _json(status, {"claim": view, "replayed": result.replayed})


@app.exception_handler(FoundError)
def handle_found_error(err: FoundError) -> Response:
    return _json(
        err.http_status,
        {
            "error": {"code": err.code, "message": err.message, "details": err.details},
            "request_id": _request_id(),
        },
    )


@app.exception_handler(Exception)
def handle_unexpected(err: Exception) -> Response:
    logger.exception("unhandled error")
    return _json(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        {
            "error": {"code": "INTERNAL", "message": "Something went wrong.", "details": {}},
            "request_id": _request_id(),
        },
    )


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_HTTP)
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return app.resolve(event, context)
