import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from config import load
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.events_stack import EventsStack
from stacks.realtime_stack import RealtimeStack

ENVS = {"dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template() -> Template:
    # Skip bundling so tests do not install packages.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    events = EventsStack(app, "Events", cfg=cfg, table=data.table, env=ENV)
    auth = AuthStack(app, "Auth", cfg=cfg, env=ENV)
    stack = RealtimeStack(
        app,
        "Realtime",
        cfg=cfg,
        table=data.table,
        bus=events.bus,
        user_pool=auth.user_pool,
        web_client=auth.web_client,
        env=ENV,
    )
    return Template.from_stack(stack)


def routes(t: Template) -> dict[str, dict]:
    return {
        r["Properties"]["RouteKey"]: r["Properties"]
        for r in t.find_resources("AWS::ApiGatewayV2::Route").values()
    }


def test_websocket_api_routes_on_action():
    t = template()
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {
            "Name": "found-dev-ws",
            "ProtocolType": "WEBSOCKET",
            "RouteSelectionExpression": "$request.body.action",
        },
    )
    assert set(routes(t)) == {"$connect", "$disconnect", "subscribe", "$default"}


def test_only_connect_is_authorized_by_token_in_query_string():
    t = template()
    found = routes(t)
    assert found["$connect"]["AuthorizationType"] == "CUSTOM"
    for key in ("$disconnect", "subscribe", "$default"):
        assert found[key].get("AuthorizationType", "NONE") == "NONE"
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Authorizer",
        {"AuthorizerType": "REQUEST", "IdentitySource": ["route.request.querystring.token"]},
    )


def test_subscribe_and_default_reply_to_the_client():
    t = template()
    responses = t.find_resources("AWS::ApiGatewayV2::RouteResponse")
    assert len(responses) == 2


def test_stage_is_prod_and_auto_deploys():
    template().has_resource_properties(
        "AWS::ApiGatewayV2::Stage", {"StageName": "prod", "AutoDeploy": True}
    )


def test_authorizer_knows_the_pool_and_client():
    template().has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "found-dev-wsauthorizer",
            "Handler": "handlers.ws_authorizer.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {"USER_POOL_ID": Match.any_value(), "USER_POOL_CLIENT_ID": Match.any_value()}
                )
            },
        },
    )


def test_ws_and_push_functions_know_the_management_endpoint():
    t = template()
    for name, handler in (
        ("found-dev-ws", "handlers.ws.handler"),
        ("found-dev-wspush", "handlers.ws_push.handler"),
    ):
        fn = t.find_resources(
            "AWS::Lambda::Function", {"Properties": {"FunctionName": name}}
        ).popitem()[1]
        props = fn["Properties"]
        assert props["Handler"] == handler
        env = props["Environment"]["Variables"]
        assert "TABLE_NAME" in env
        assert "/prod" in json.dumps(env["WS_ENDPOINT"])


def test_push_listens_for_claims_alerts_and_reviews_with_dlq():
    t = template()
    rules = t.find_resources("AWS::Events::Rule")
    by_name = {r["Properties"]["Name"]: r["Properties"] for r in rules.values()}
    expected = {
        "found-dev-push-claim": "CLAIM",
        "found-dev-push-alert": "ALERT",
        "found-dev-push-review": "REVIEW_ITEM",
    }
    assert set(by_name) == set(expected)
    for name, entity in expected.items():
        pattern = by_name[name]["EventPattern"]
        assert pattern["detail"]["dynamodb"]["NewImage"]["entity_type"]["S"] == [entity]
        (target,) = by_name[name]["Targets"]
        assert "WsPushDlq" in json.dumps(target["DeadLetterConfig"])
    t.has_resource_properties("AWS::SQS::Queue", {"QueueName": "found-dev-wspush-dlq"})


def test_connection_management_is_limited_to_this_stage():
    t = template()
    statements = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if s["Action"] == "execute-api:ManageConnections"
    ]
    assert len(statements) == 2
    for statement in statements:
        assert "/prod/*/@connections/*" in json.dumps(statement["Resource"])


def test_stack_exports_websocket_url():
    assert "WebSocketUrl" in template().find_outputs("*")
