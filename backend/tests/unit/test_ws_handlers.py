import json
from datetime import UTC, datetime

import pytest
from boto3.dynamodb.types import TypeSerializer

from found_core import container
from found_core.adapters.cognito_jwt import InvalidToken
from found_core.adapters.dynamodb import alert_item
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.models import Alert
from found_core.events import EVENT_DETAIL_TYPE, EVENT_SOURCE
from found_core.services.realtime import ConnectionService, PushService
from handlers import ws, ws_authorizer, ws_push

ARN = "arn:aws:execute-api:ap-south-1:111111111111:abc/prod/$connect"


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class Context:
    function_name = "ws"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:ws"
    aws_request_id = "req-1"


class FakeVerifier:
    def verify(self, token):
        if token != "good":
            raise InvalidToken("bad token")
        return {"sub": "fam_1", "cognito:groups": ["family"], "token_use": "id"}


class FakeGateway:
    def __init__(self):
        self.sent = []

    def send(self, connection_id, data):
        self.sent.append((connection_id, json.loads(data)))
        return True

    def close(self, connection_id):
        pass


@pytest.fixture
def world(monkeypatch):
    repo = InMemoryFoundRepository()
    repo.add_incident("inc_1")
    gateway = FakeGateway()
    connections = ConnectionService(repo, gateway, clock=FixedClock())
    push = PushService(repo, gateway, clock=FixedClock())
    monkeypatch.setattr(container, "token_verifier", lambda: FakeVerifier())
    monkeypatch.setattr(container, "connection_service", lambda: connections)
    monkeypatch.setattr(container, "push_service", lambda: push)
    return repo, gateway


def authorize(token):
    query = {"token": token} if token is not None else None
    return ws_authorizer.handler({"methodArn": ARN, "queryStringParameters": query}, Context())


def test_authorizer_allows_valid_token_and_passes_identity(world):
    policy = authorize("good")
    statement = policy["policyDocument"]["Statement"][0]
    assert statement == {"Action": "execute-api:Invoke", "Effect": "Allow", "Resource": ARN}
    assert policy["principalId"] == "fam_1"
    assert policy["context"] == {"user_id": "fam_1", "groups": "family", "org_id": ""}


@pytest.mark.parametrize("token", ["bad", "", None])
def test_authorizer_denies_bad_or_missing_token(world, token):
    policy = authorize(token)
    assert policy["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in policy


def ws_event(route, connection_id="c1", body=None, authorizer=None):
    context = {"routeKey": route, "connectionId": connection_id}
    if authorizer is not None:
        context["authorizer"] = authorizer
    return {"requestContext": context, "body": json.dumps(body) if body is not None else None}


STAFF = {"user_id": "rev_1", "groups": "reviewer", "org_id": "", "principalId": "rev_1"}


def test_connect_subscribe_disconnect(world):
    repo, _ = world
    assert ws.handler(ws_event("$connect", authorizer=STAFF), Context()) == {"statusCode": 200}
    stored = repo.get_connection("c1")
    assert stored.user_id == "rev_1" and stored.groups == ("reviewer",)

    reply = ws.handler(ws_event("subscribe", body={"incident_id": "inc_1"}), Context())
    assert reply["statusCode"] == 200
    assert json.loads(reply["body"]) == {"type": "subscribed", "incident_id": "inc_1"}

    assert ws.handler(ws_event("$disconnect"), Context()) == {"statusCode": 200}
    assert repo.connections == {}


def test_connect_without_identity_is_refused(world):
    repo, _ = world
    assert ws.handler(ws_event("$connect", authorizer={}), Context()) == {"statusCode": 401}
    assert repo.connections == {}


def test_subscribe_errors_are_replied_not_raised(world):
    ws.handler(ws_event("$connect", authorizer=STAFF), Context())
    reply = ws.handler(ws_event("subscribe", body={"incident_id": "inc_x"}), Context())
    assert reply["statusCode"] == 404
    assert json.loads(reply["body"])["error"]["code"] == "NOT_FOUND"
    reply = ws.handler(ws_event("subscribe", body=None), Context())
    assert json.loads(reply["body"])["error"]["code"] == "BAD_REQUEST"


def test_unknown_action_gets_an_error_reply(world):
    reply = ws.handler(ws_event("$default", body={"action": "dance"}), Context())
    assert reply["statusCode"] == 400
    assert json.loads(reply["body"])["error"]["message"] == "Unknown action."


_serializer = TypeSerializer()


def bus_event(item):
    image = {k: _serializer.serialize(v) for k, v in item.items()}
    return {
        "id": "evt-bus",
        "source": EVENT_SOURCE,
        "detail-type": EVENT_DETAIL_TYPE,
        "detail": {"eventID": "evt-1", "eventName": "INSERT", "dynamodb": {"NewImage": image}},
    }


def test_push_handler_sends_alert_to_its_user(world):
    _, gateway = world
    ws.handler(
        ws_event("$connect", "tab", authorizer={"user_id": "fam_1", "groups": "family"}),
        Context(),
    )
    alert = Alert(
        id="alr_1",
        incident_id="inc_1",
        subject_id="per_1",
        subscription_id="sub_1",
        claim_id="clm_1",
        user_id="fam_1",
        relation="UPDATE",
        severity="info",
        message="Newer report for Maya Rawat.",
        delivery_status="NOT_REQUIRED",
        created_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
    )
    result = ws_push.handler(bus_event(alert_item(alert)), Context())
    assert result == {"status": "pushed", "sent": 1, "gone": 0, "failed": 0}
    assert gateway.sent == [
        (
            "tab",
            {
                "type": "alert.created",
                "alert_id": "alr_1",
                "subject_id": "per_1",
                "severity": "info",
                "message": "Newer report for Maya Rawat.",
            },
        )
    ]


def test_push_handler_ignores_foreign_events(world):
    result = ws_push.handler({"source": "aws.s3", "detail-type": "x", "detail": {}}, Context())
    assert result == {"status": "ignored"}
