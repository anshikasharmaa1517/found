import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.models import Organization
from found_core.services.ingest import IngestService
from found_core.services.reports import ReportService
from handlers import api


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class Context:
    function_name = "api"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:api"
    aws_request_id = "req-1"


BODY = {
    "subject": {"type": "PERSON", "new": {"name": "Maya Rawat", "age": 24}},
    "claim_type": "MISSING",
    "original_text": "Maya Rawat, 24, missing since the bridge collapse.",
    "external_reference": "CH-1",
    "reported_at": "2026-10-02T21:10:00+05:30",
}
PUBLISHER_CLAIMS = {"sub": "user_1", "cognito:groups": "[publisher]", "custom:org_id": "org_h"}


def event(method, path, body=None, claims=None, raw_body=None, query=None):
    authorizer = {"jwt": {"claims": claims, "scopes": None}} if claims is not None else None
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": urlencode(query or {}),
        **({"queryStringParameters": query} if query else {}),
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "accountId": "111111111111",
            "apiId": "api",
            "domainName": "api.example.org",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "test",
            },
            "requestId": "req-abc",
            "routeKey": f"{method} {path}",
            "stage": "$default",
            "time": "05/Oct/2026:10:15:00 +0000",
            "timeEpoch": 1791195300000,
            **({"authorizer": authorizer} if authorizer else {}),
        },
        "body": raw_body if raw_body is not None else (json.dumps(body) if body else None),
        "isBase64Encoded": False,
    }


@pytest.fixture
def repo(monkeypatch):
    r = InMemoryFoundRepository()
    r.add_incident("inc_1")
    r.add_organization(
        Organization(
            id="org_h",
            incident_id="inc_1",
            name="Central Hospital Demo",
            name_norm="central hospital demo",
            org_type="HOSPITAL",
        )
    )
    service = ReportService(r, IngestService(r, clock=FixedClock(), sleep=lambda _: None))
    monkeypatch.setattr(container, "report_service", lambda: service)
    return r


def call(evt):
    resp = api.handler(evt, Context())
    return resp["statusCode"], json.loads(resp["body"]), resp.get("headers", {})


def publish(body=BODY, claims=PUBLISHER_CLAIMS, **kwargs):
    return call(event("POST", "/v1/incidents/inc_1/reports", body, claims, **kwargs))


def test_health():
    status, body, _ = call(event("GET", "/v1/health"))
    assert status == 200 and body == {"status": "ok"}


def test_publish_returns_201_with_claim_view(repo):
    status, body, headers = publish()
    assert status == 201
    assert body["replayed"] is False
    claim = body["claim"]
    assert claim["seq"] == 1
    assert claim["source"]["name"] == "Central Hospital Demo"
    assert claim["source"]["type"] == "HOSPITAL"
    assert claim["reported_at"] == "2026-10-02T15:40:00Z"
    assert claim["reported_at_raw"] == "2026-10-02T21:10:00+05:30"
    assert claim["payload_hash"].startswith("sha256:")
    assert "original_text" not in claim
    assert headers["x-request-id"] == "req-abc"


def test_retry_returns_200_replayed(repo):
    publish()
    status, body, _ = publish()
    assert status == 200 and body["replayed"] is True
    assert len(repo.claims) == 1


def test_changed_content_same_reference_is_409(repo):
    publish()
    status, body, _ = publish({**BODY, "original_text": "Different."})
    assert status == 409
    assert body["error"]["code"] == "REFERENCE_CONFLICT"
    assert body["error"]["details"]["existing_claim_id"]
    assert body["request_id"] == "req-abc"


def test_invalid_body_is_422_with_field_errors(repo):
    status, body, _ = publish({**BODY, "external_reference": "bad ref!"})
    assert status == 422
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["details"]["errors"]


def test_org_in_body_is_422(repo):
    status, body, _ = publish({**BODY, "org_id": "org_other"})
    assert status == 422
    assert repo.claims == {}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]"])
def test_non_object_body_is_400(repo, raw):
    status, body, _ = publish(raw_body=raw)
    assert status == 400 and body["error"]["code"] == "BAD_REQUEST"


def test_family_member_is_403(repo):
    status, body, _ = publish(claims={"sub": "u2", "cognito:groups": "[family]"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_missing_token_claims_is_401(repo):
    status, body, _ = publish(claims=None)
    assert status == 401 and body["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_subject_is_404(repo):
    status, _, _ = publish({**BODY, "subject": {"type": "PERSON", "id": "per_missing"}})
    assert status == 404


def test_unexpected_error_is_500_without_details(repo, monkeypatch):
    def boom():
        raise RuntimeError("secret internals")

    monkeypatch.setattr(container, "report_service", boom)
    status, body, _ = publish()
    assert status == 500
    assert body["error"]["code"] == "INTERNAL"
    assert "secret" not in json.dumps(body)
