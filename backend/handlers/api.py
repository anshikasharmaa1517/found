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
from found_core.domain.models import Alert, Claim, Subject, Subscription
from found_core.domain.normalize import excerpt
from found_core.domain.visibility import SENSITIVE_NOTICE
from found_core.services.investigations import InvestigationDetail
from found_core.services.people import PersonProfile, TimelineEntry
from found_core.services.review import ReviewEntry

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


def _body(optional: bool = False) -> dict[str, Any]:
    if optional and not app.current_event.body:
        return {}
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
        "location_id": data["location_id"],
        "payload_hash": data["payload_hash"],
    }


def _query(name: str) -> str | None:
    return app.current_event.get_query_string_value(name)


def person_view(person: Subject) -> dict[str, Any]:
    return {"id": person.id, "name": person.display_name, "age": person.age}


def _source_name(profile: PersonProfile, source_id: str) -> str:
    source = profile.sources.get(source_id)
    return source.name if source else source_id


def summary_view(profile: PersonProfile) -> dict[str, Any]:
    summary = profile.summary
    return {
        "label": summary.label,
        "basis": summary.basis,
        "cited_claim_id": summary.cited_claim_id,
        "conflicts": [
            {"claim_id": c.id, "withheld": True, "notice": SENSITIVE_NOTICE}
            if c.id in profile.withheld
            else {
                "claim_id": c.id,
                "claim_type": c.claim_type,
                "source": _source_name(profile, c.source_id),
                "withheld": False,
            }
            for c in profile.conflicts
        ],
        "needs_review": summary.needs_review,
    }


def entry_view(profile: PersonProfile, entry: TimelineEntry) -> dict[str, Any]:
    claim = entry.claim
    reported_at = claim.model_dump(mode="json")["reported_at"]
    if entry.withheld:
        return {
            "claim_id": claim.id,
            "seq": claim.seq,
            "reported_at": reported_at,
            "withheld": True,
            "notice": SENSITIVE_NOTICE,
        }
    return {
        "claim_id": claim.id,
        "seq": claim.seq,
        "claim_type": claim.claim_type,
        "value": claim.value,
        "source_id": claim.source_id,
        "source": _source_name(profile, claim.source_id),
        "reported_at": reported_at,
        "relation": entry.relation.value,
        "excerpt": excerpt(claim.original_text),
        "withheld": False,
    }


def subscription_view(sub: Subscription) -> dict[str, Any]:
    data = sub.model_dump(mode="json")
    return {
        "id": sub.id,
        "person_id": sub.subject_id,
        "channel_inapp": True,
        "channel_sms": sub.channel_sms,
        "channel_email": sub.channel_email,
        "phone_e164": sub.phone_e164,
        "email": sub.email,
        "active": sub.active,
        "created_at": data["created_at"],
    }


def alert_view(alert: Alert) -> dict[str, Any]:
    data = alert.model_dump(mode="json")
    return {
        "id": alert.id,
        "incident_id": alert.incident_id,
        "person_id": alert.subject_id,
        "claim_id": alert.claim_id,
        "relation": data["relation"],
        "severity": data["severity"],
        "message": alert.message,
        "delivery_status": data["delivery_status"],
        "created_at": data["created_at"],
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


@app.get("/v1/incidents/<incident_id>/people")
def list_people(incident_id: str) -> Response:
    page = container.people_service().list_people(
        _caller(),
        incident_id,
        q=_query("q"),
        age=_query("age"),
        limit=_query("limit"),
        cursor=_query("cursor"),
    )
    return _json(
        HTTPStatus.OK,
        {"people": [person_view(p) for p in page.people], "next_cursor": page.next_cursor},
    )


@app.get("/v1/people/<person_id>")
def get_person(person_id: str) -> Response:
    profile = container.people_service().profile(_caller(), person_id)
    person = profile.person
    return _json(
        HTTPStatus.OK,
        {
            "person": {
                **person_view(person),
                "incident_id": person.incident_id,
                "notes": person.notes,
                "report_count": profile.claim_count,
            },
            "summary": summary_view(profile),
            # Identity decisions arrive with the resolver; until then there are none.
            "identity": [],
        },
    )


@app.get("/v1/people/<person_id>/timeline")
def get_timeline(person_id: str) -> Response:
    timeline = container.people_service().timeline(
        _caller(),
        person_id,
        order=_query("order"),
        limit=_query("limit"),
        cursor=_query("cursor"),
    )
    profile = timeline.profile
    return _json(
        HTTPStatus.OK,
        {
            "person": person_view(profile.person),
            "summary": summary_view(profile),
            "identity": [],
            "entries": [entry_view(profile, e) for e in timeline.entries],
            "next_cursor": timeline.next_cursor,
        },
    )


@app.get("/v1/incidents/<incident_id>/map")
def incident_map(incident_id: str) -> Response:
    result = container.map_service().incident_map(_caller(), incident_id)
    counts = result.counts
    return _json(
        HTTPStatus.OK,
        {
            "places": [
                {
                    "location_id": p.location.id,
                    "name": p.location.name,
                    "lat": p.location.lat,
                    "lon": p.location.lon,
                    "reports": p.reports,
                    "by_status": p.by_status,
                }
                for p in counts.places
            ],
            "located_reports": counts.located_reports,
            "unlocated_reports": counts.unlocated_reports,
            "caveat": counts.caveat,
            "updated_at": result.updated_at.isoformat().replace("+00:00", "Z"),
        },
    )


@app.post("/v1/people/<person_id>/subscriptions")
def follow_person(person_id: str) -> Response:
    caller = _caller()
    body = _body(optional=True)
    result = container.subscription_service().follow(caller, person_id, body)
    status = HTTPStatus.CREATED if result.created else HTTPStatus.OK
    return _json(status, {"subscription": subscription_view(result.subscription)})


@app.delete("/v1/subscriptions/<subscription_id>")
def unfollow(subscription_id: str) -> Response:
    container.subscription_service().unfollow(_caller(), subscription_id)
    return Response(
        status_code=HTTPStatus.NO_CONTENT, body="", headers={"x-request-id": _request_id()}
    )


@app.get("/v1/me/subscriptions")
def my_subscriptions() -> Response:
    subs = container.subscription_service().my_subscriptions(_caller())
    return _json(HTTPStatus.OK, {"subscriptions": [subscription_view(s) for s in subs]})


@app.get("/v1/me/alerts")
def my_alerts() -> Response:
    page = container.subscription_service().alert_feed(
        _caller(), limit=_query("limit"), cursor=_query("cursor")
    )
    return _json(
        HTTPStatus.OK,
        {"alerts": [alert_view(a) for a in page.alerts], "next_cursor": page.next_cursor},
    )


def _iso(value: Any) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def investigation_view(detail: InvestigationDetail) -> dict[str, Any]:
    inv = detail.investigation
    data = inv.model_dump(mode="json")
    finding = None
    if inv.attribution is not None:
        referenced = None
        if inv.referenced_source_id:
            source = detail.referenced_source
            referenced = {"id": inv.referenced_source_id, "name": source.name if source else None}
        finding = {
            "attribution": data["attribution"],
            "referenced_source": referenced,
            "comparison": data["comparison"],
            "summary": inv.summary,
            "citations": data["citations"],
        }
    duration_ms = (
        int((inv.finished_at - inv.started_at).total_seconds() * 1000)
        if inv.started_at and inv.finished_at
        else None
    )
    return {
        "id": inv.id,
        "incident_id": inv.incident_id,
        "claim_id": inv.claim_id,
        "mode": data["mode"],
        "status": data["status"],
        "model_id": inv.model_id,
        "prompt_version": inv.prompt_version,
        "agent_version": inv.agent_version,
        "finding": finding,
        "outcome_reasons": list(inv.outcome_reasons),
        "failure_reason": inv.failure_reason,
        "usage": {
            "tool_calls": inv.tool_calls,
            "model_calls": inv.model_calls,
            "input_tokens": inv.input_tokens,
            "output_tokens": inv.output_tokens,
            "usage_source": inv.usage_source,
        },
        "timing": {
            "queued_at": _iso(inv.queued_at),
            "started_at": _iso(inv.started_at),
            "finished_at": _iso(inv.finished_at),
            "duration_ms": duration_ms,
        },
        "steps": [
            {
                "seq": s.seq,
                "kind": s.kind.value,
                "tool": s.tool_name,
                "summary": s.output_summary,
                "duration_ms": s.duration_ms,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "error_code": s.error_code,
            }
            for s in detail.steps
        ],
        "review": None
        if inv.review_status is None
        else {
            "decision": data["review_status"],
            "by": inv.reviewed_by,
            "note": inv.review_note,
            "at": _iso(inv.reviewed_at),
        },
    }


@app.post("/v1/claims/<claim_id>/investigations")
def start_investigation(claim_id: str) -> Response:
    caller = _caller()
    body = _body(optional=True)
    force_live = body.get("force_live", False)
    if set(body) - {"force_live"} or not isinstance(force_live, bool):
        raise BadRequest("The body may only hold force_live, true or false.")
    result = container.investigation_service().start(caller, claim_id, force_live=force_live)
    inv = result.investigation
    if not result.created:
        return _json(
            HTTPStatus.OK,
            {
                "investigation_id": inv.id,
                "mode": result.mode.value,
                "status": inv.status.value,
                "original_run_at": _iso(inv.finished_at),
            },
        )
    return _json(
        HTTPStatus.ACCEPTED,
        {
            "investigation_id": inv.id,
            "mode": result.mode.value,
            "status": inv.status.value,
            "ws_topic": f"investigation:{inv.id}",
        },
    )


@app.get("/v1/investigations/<investigation_id>")
def get_investigation(investigation_id: str) -> Response:
    detail = container.investigation_service().get(_caller(), investigation_id)
    return _json(HTTPStatus.OK, investigation_view(detail))


def review_entry_view(entry: ReviewEntry) -> dict[str, Any]:
    item = entry.item
    data = item.model_dump(mode="json")
    view: dict[str, Any] = {
        "id": item.id,
        "type": data["item_type"],
        "status": data["status"],
        "priority": item.priority,
        "created_at": data["created_at"],
        "ref_id": item.ref_id,
        "resolved_by": item.resolved_by,
        "resolved_at": data["resolved_at"],
        "note": item.note,
        "person": person_view(entry.subject) if entry.subject else None,
        "claim": None,
        "investigation": None,
    }
    if entry.claim is not None:
        claim = entry.claim
        view["claim"] = {
            "id": claim.id,
            "claim_type": claim.claim_type,
            "source": entry.source.name if entry.source else claim.source_id,
            "reported_at": claim.model_dump(mode="json")["reported_at"],
            # Reviewers see sensitive reports in full; this route is reviewer-only.
            "excerpt": excerpt(claim.original_text),
        }
    if entry.investigation is not None:
        inv = entry.investigation
        view["investigation"] = {
            "id": inv.id,
            "status": inv.status.value,
            "attribution": inv.attribution.value if inv.attribution else None,
            "comparison": inv.comparison.value if inv.comparison else None,
            "outcome_reasons": list(inv.outcome_reasons),
        }
    return view


@app.get("/v1/incidents/<incident_id>/review-queue")
def review_queue(incident_id: str) -> Response:
    page = container.review_service().queue(
        _caller(),
        incident_id,
        item_type=_query("type"),
        status=_query("status"),
        limit=_query("limit"),
        cursor=_query("cursor"),
    )
    return _json(
        HTTPStatus.OK,
        {
            "items": [review_entry_view(e) for e in page.entries],
            "next_cursor": page.next_cursor,
        },
    )


@app.post("/v1/incidents/<incident_id>/review-items/<review_id>/resolve")
def resolve_review_item(incident_id: str, review_id: str) -> Response:
    caller = _caller()
    body = _body(optional=True)
    result = container.review_service().resolve(caller, incident_id, review_id, body)
    item = result.item
    return _json(
        HTTPStatus.OK,
        {
            "id": item.id,
            "status": item.status.value,
            "resolved_by": item.resolved_by,
            "alerts_released": result.alerts_released,
        },
    )


@app.post("/v1/investigations/<investigation_id>/review")
def review_investigation(investigation_id: str) -> Response:
    caller = _caller()
    body = _body()
    container.review_service().review_finding(caller, investigation_id, body)
    detail = container.investigation_service().get(caller, investigation_id)
    return _json(HTTPStatus.OK, investigation_view(detail))


@app.get("/v1/incidents/<incident_id>/activity")
def incident_activity(incident_id: str) -> Response:
    entries = container.demo_service().activity(_caller(), incident_id)
    return _json(
        HTTPStatus.OK,
        {
            "activity": [
                {
                    "id": a.id,
                    "actor": a.actor,
                    "component": a.component,
                    "message": a.message,
                    "target_ids": list(a.target_ids),
                    "at": _iso(a.created_at),
                }
                for a in entries
            ]
        },
    )


@app.post("/v1/admin/incidents/<incident_id>/reset")
def reset_demo(incident_id: str) -> Response:
    container.demo_service().request_reset(_caller(), incident_id)
    return _json(HTTPStatus.ACCEPTED, {"incident_id": incident_id, "status": "RESETTING"})


@app.get("/v1/admin/investigations/<investigation_id>/recording")
def investigation_recording(investigation_id: str) -> Response:
    return _json(HTTPStatus.OK, container.demo_service().recording(_caller(), investigation_id))


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
