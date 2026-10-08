import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.cursor import CursorCodec
from found_core.domain.models import Alert, Organization
from found_core.domain.places import CAVEAT
from found_core.services.ingest import IngestService
from found_core.services.map import MapService
from found_core.services.people import PeopleService
from found_core.services.reports import ReportService
from found_core.services.subscriptions import SubscriptionService
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
    people = PeopleService(r, CursorCodec(b"k" * 32))
    monkeypatch.setattr(container, "people_service", lambda: people)
    subs = SubscriptionService(r, CursorCodec(b"k" * 32), clock=FixedClock())
    monkeypatch.setattr(container, "subscription_service", lambda: subs)
    maps = MapService(r, clock=FixedClock())
    monkeypatch.setattr(container, "map_service", lambda: maps)
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


REVIEWER_CLAIMS = {"sub": "rev_1", "cognito:groups": "[reviewer]"}


def get(path, query=None, claims=REVIEWER_CLAIMS):
    return call(event("GET", path, claims=claims, query=query))


@pytest.fixture
def maya(repo):
    _, body, _ = publish()
    pid = body["claim"]["subject_id"]
    publish(
        {
            **BODY,
            "subject": {"type": "PERSON", "id": pid},
            "claim_type": "FOUND_SAFE",
            "original_text": "Maya Rawat admitted to ward 3. " + "Stable condition. " * 20,
            "external_reference": "CH-2",
            "reported_at": "2026-10-03T07:40:00+05:30",
        }
    )
    return pid


def test_people_list_and_search(maya):
    status, body, headers = get("/v1/incidents/inc_1/people", {"q": "rawat", "age": "25"})
    assert status == 200
    assert body == {"people": [{"id": maya, "name": "Maya Rawat", "age": 24}], "next_cursor": None}
    assert headers["x-request-id"] == "req-abc"


def test_people_list_pages(maya, repo):
    publish(
        {
            **BODY,
            "subject": {"type": "PERSON", "new": {"name": "Asha Devi"}},
            "external_reference": "CH-3",
        }
    )
    _, first, _ = get("/v1/incidents/inc_1/people", {"limit": "1"})
    assert [p["name"] for p in first["people"]] == ["Asha Devi"]
    _, second, _ = get("/v1/incidents/inc_1/people", {"limit": "1", "cursor": first["next_cursor"]})
    assert [p["name"] for p in second["people"]] == ["Maya Rawat"]
    assert second["next_cursor"] is None


def test_people_bad_limit_is_400(repo):
    status, body, _ = get("/v1/incidents/inc_1/people", {"limit": "500"})
    assert status == 400 and body["error"]["code"] == "BAD_REQUEST"


def test_people_unknown_incident_is_404(repo):
    status, _, _ = get("/v1/incidents/inc_x/people")
    assert status == 404


def test_people_requires_sign_in(repo):
    status, _, _ = get("/v1/incidents/inc_1/people", claims=None)
    assert status == 401


def test_person_profile(maya):
    status, body, _ = get(f"/v1/people/{maya}")
    assert status == 200
    assert body["person"] == {
        "id": maya,
        "name": "Maya Rawat",
        "age": 24,
        "incident_id": "inc_1",
        "notes": None,
        "report_count": 2,
    }
    assert body["summary"]["label"] == "Reported found safe"
    assert body["summary"]["conflicts"] == []
    assert body["identity"] == []


def test_timeline_matches_design_shape(maya):
    status, body, _ = get(f"/v1/people/{maya}/timeline")
    assert status == 200
    assert body["person"] == {"id": maya, "name": "Maya Rawat", "age": 24}
    summary = body["summary"]
    assert summary["basis"] == "Latest dated status report"
    assert summary["cited_claim_id"] == body["entries"][1]["claim_id"]
    assert summary["needs_review"] is False
    first, second = body["entries"]
    assert first["relation"] == "FIRST" and second["relation"] == "UPDATE"
    assert second["source"] == "Central Hospital Demo"
    assert second["reported_at"] == "2026-10-03T02:10:00Z"
    assert second["excerpt"].endswith("...") and len(second["excerpt"]) <= 163
    assert "original_text" not in second
    assert body["next_cursor"] is None


def test_timeline_desc_with_cursor(maya):
    _, first, _ = get(f"/v1/people/{maya}/timeline", {"order": "desc", "limit": "1"})
    assert first["entries"][0]["claim_type"] == "FOUND_SAFE"
    _, second, _ = get(
        f"/v1/people/{maya}/timeline",
        {"order": "desc", "limit": "1", "cursor": first["next_cursor"]},
    )
    assert second["entries"][0]["claim_type"] == "MISSING"
    assert second["next_cursor"] is None


def test_tampered_cursor_is_400(maya):
    _, first, _ = get(f"/v1/people/{maya}/timeline", {"limit": "1"})
    status, body, _ = get(
        f"/v1/people/{maya}/timeline", {"limit": "1", "cursor": first["next_cursor"] + "x"}
    )
    assert status == 400 and body["error"]["code"] == "BAD_REQUEST"


def test_unknown_person_is_404(repo):
    status, body, _ = get("/v1/people/per_missing/timeline")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_publisher_of_other_incident_is_403(maya, repo):
    claims = {"sub": "u9", "cognito:groups": "[publisher]", "custom:org_id": "org_other"}
    status, _, _ = get(f"/v1/people/{maya}", claims=claims)
    assert status == 403


FAMILY_CLAIMS = {"sub": "fam_1", "cognito:groups": "[family]"}


def test_follow_unfollow_and_list(maya):
    path = f"/v1/people/{maya}/subscriptions"
    body = {"channel_sms": True, "phone_e164": "+919876543210"}
    status, created, _ = call(event("POST", path, body, FAMILY_CLAIMS))
    assert status == 201
    sub = created["subscription"]
    assert sub["person_id"] == maya and sub["channel_inapp"] is True
    assert sub["channel_sms"] is True and sub["created_at"] == "2026-10-05T10:15:00Z"

    status, again, _ = call(event("POST", path, {}, FAMILY_CLAIMS))
    assert status == 200 and again["subscription"]["id"] == sub["id"]

    _, mine, _ = get("/v1/me/subscriptions", claims=FAMILY_CLAIMS)
    assert [s["id"] for s in mine["subscriptions"]] == [sub["id"]]

    resp = api.handler(
        event("DELETE", f"/v1/subscriptions/{sub['id']}", claims=FAMILY_CLAIMS), Context()
    )
    assert resp["statusCode"] == 204 and not resp.get("body")
    _, mine, _ = get("/v1/me/subscriptions", claims=FAMILY_CLAIMS)
    assert mine["subscriptions"] == []


def test_follow_with_sms_but_no_phone_is_422(maya):
    status, body, _ = call(
        event("POST", f"/v1/people/{maya}/subscriptions", {"channel_sms": True}, FAMILY_CLAIMS)
    )
    assert status == 422 and body["error"]["code"] == "VALIDATION_FAILED"


def test_follow_requires_family(maya):
    status, _, _ = call(event("POST", f"/v1/people/{maya}/subscriptions", {}, REVIEWER_CLAIMS))
    assert status == 403


def test_unfollow_unknown_is_404(repo):
    status, _, _ = call(event("DELETE", "/v1/subscriptions/sub_x", claims=FAMILY_CLAIMS))
    assert status == 404


def test_alert_feed_view(repo):
    repo.put_alert_if_absent(
        Alert(
            id="alr_1",
            incident_id="inc_1",
            subject_id="per_1",
            subscription_id="sub_1",
            claim_id="clm_1",
            user_id="fam_1",
            relation="FIRST",
            severity="high",
            message="A sensitive report was received.",
            delivery_status="HELD",
            held_reason="SENSITIVE_STATUS",
            created_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
        )
    )
    status, body, _ = get("/v1/me/alerts", claims=FAMILY_CLAIMS)
    assert status == 200
    assert body == {
        "alerts": [
            {
                "id": "alr_1",
                "incident_id": "inc_1",
                "person_id": "per_1",
                "claim_id": "clm_1",
                "relation": "FIRST",
                "severity": "high",
                "message": "A sensitive report was received.",
                "delivery_status": "HELD",
                "created_at": "2026-10-05T10:15:00Z",
            }
        ],
        "next_cursor": None,
    }


def test_alert_feed_bad_cursor_is_400(repo):
    status, body, _ = get("/v1/me/alerts", {"cursor": "abc.def"}, claims=FAMILY_CLAIMS)
    assert status == 400 and body["error"]["code"] == "BAD_REQUEST"


def test_publish_with_location_and_read_the_map(repo):
    located = {**BODY, "location": {"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354}}
    status, body, _ = publish(located)
    assert status == 201 and body["claim"]["location_id"].startswith("loc_")
    location_id = body["claim"]["location_id"]
    publish({**BODY, "external_reference": "CH-9"})

    status, body, _ = get("/v1/incidents/inc_1/map")
    assert status == 200
    assert body == {
        "places": [
            {
                "location_id": location_id,
                "name": "Old Bridge",
                "lat": 30.7268,
                "lon": 78.4354,
                "reports": 1,
                "by_status": {"MISSING": 1, "FOUND_SAFE": 0, "NEEDS_REVIEW": 0, "OTHER": 0},
            }
        ],
        "located_reports": 1,
        "unlocated_reports": 1,
        "caveat": CAVEAT,
        "updated_at": "2026-10-05T10:15:00Z",
    }


def test_map_of_unknown_incident_is_404(repo):
    status, _, _ = get("/v1/incidents/inc_x/map")
    assert status == 404


def test_location_with_half_a_coordinate_is_422(repo):
    status, body, _ = publish({**BODY, "location": {"name": "Old Bridge", "lat": 30.7}})
    assert status == 422 and body["error"]["code"] == "VALIDATION_FAILED"
