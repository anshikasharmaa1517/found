import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from config import load
from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack

ENVS = {"dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template() -> Template:
    # Skip bundling so tests do not install packages.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    auth = AuthStack(app, "Auth", cfg=cfg, env=ENV)
    agent = AgentStack(app, "Agent", cfg=cfg, table=data.table, env=ENV)
    api = ApiStack(
        app,
        "Api",
        cfg=cfg,
        table=data.table,
        run_queue=agent.run_queue,
        model_id=agent.model_id,
        user_pool=auth.user_pool,
        web_client=auth.web_client,
        env=ENV,
    )
    return Template.from_stack(api)


def routes(t: Template) -> dict[str, dict]:
    return {
        r["Properties"]["RouteKey"]: r["Properties"]
        for r in t.find_resources("AWS::ApiGatewayV2::Route").values()
    }


def test_function_runtime_and_handler():
    t = template()
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "found-dev-api",
            "Runtime": "python3.12",
            "Architectures": ["arm64"],
            "Handler": "handlers.api.handler",
            "Timeout": 10,
            "TracingConfig": {"Mode": "Active"},
            "Environment": {
                "Variables": Match.object_like({"TABLE_NAME": Match.any_value()})
            },
        },
    )


def test_reports_route_requires_jwt_and_health_is_open():
    found = routes(template())
    reports = found["POST /v1/incidents/{incident_id}/reports"]
    assert reports["AuthorizationType"] == "JWT"
    health = found["GET /v1/health"]
    assert health.get("AuthorizationType", "NONE") == "NONE"


def test_signed_in_routes_require_jwt():
    found = routes(template())
    for key in (
        "GET /v1/incidents/{incident_id}/people",
        "GET /v1/people/{person_id}",
        "GET /v1/people/{person_id}/timeline",
        "GET /v1/incidents/{incident_id}/map",
        "POST /v1/people/{person_id}/subscriptions",
        "DELETE /v1/subscriptions/{subscription_id}",
        "GET /v1/me/subscriptions",
        "GET /v1/me/alerts",
        "POST /v1/claims/{claim_id}/investigations",
        "GET /v1/investigations/{investigation_id}",
    ):
        assert found[key]["AuthorizationType"] == "JWT"


def test_cors_allows_delete_for_unfollow():
    t = template()
    api = next(iter(t.find_resources("AWS::ApiGatewayV2::Api").values()))
    assert "DELETE" in api["Properties"]["CorsConfiguration"]["AllowMethods"]


def test_cursor_secret_is_generated_and_readable_by_function():
    t = template()
    t.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {"GenerateSecretString": {"PasswordLength": 64, "ExcludePunctuation": True}},
    )
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like({"CURSOR_SECRET_ARN": {"Ref": Match.any_value()}})
            }
        },
    )
    statements = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert any("secretsmanager:GetSecretValue" in s["Action"] for s in statements)


def test_jwt_authorizer_checks_cognito_issuer_and_client_audience():
    t = template()
    authorizer = next(iter(t.find_resources("AWS::ApiGatewayV2::Authorizer").values()))
    props = authorizer["Properties"]
    assert props["AuthorizerType"] == "JWT"
    assert props["IdentitySource"] == ["$request.header.Authorization"]
    issuer = props["JwtConfiguration"]["Issuer"]
    assert "cognito-idp.ap-south-1.amazonaws.com" in str(issuer)
    assert len(props["JwtConfiguration"]["Audience"]) == 1


def test_throttling_matches_design():
    t = template()
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "DefaultRouteSettings": {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40},
            "RouteSettings": {
                "POST /v1/incidents/{incident_id}/reports": {
                    "ThrottlingRateLimit": 10,
                    "ThrottlingBurstLimit": 20,
                },
                "POST /v1/claims/{claim_id}/investigations": {
                    "ThrottlingRateLimit": 2,
                    "ThrottlingBurstLimit": 5,
                },
            },
        },
    )


def test_cors_allows_configured_origins_only():
    t = template()
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {
            "CorsConfiguration": Match.object_like(
                {
                    "AllowOrigins": ["http://localhost:5173"],
                    "ExposeHeaders": ["x-request-id"],
                }
            )
        },
    )


def test_function_can_use_table():
    t = template()
    policies = t.find_resources("AWS::IAM::Policy")
    actions = {
        a
        for p in policies.values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    }
    assert {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"} <= actions
    assert "dynamodb:ConditionCheckItem" in actions


def test_log_retention_is_one_month():
    template().has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 30})


def test_stack_exports_api_url():
    assert "ApiUrl" in template().find_outputs("*")


def test_function_can_queue_runs_with_the_agents_model():
    t = template()
    env = next(
        r["Properties"]["Environment"]["Variables"]
        for r in t.find_resources("AWS::Lambda::Function").values()
        if r["Properties"].get("FunctionName") == "found-dev-api"
    )
    assert "RUN_QUEUE_URL" in env and "MODEL_ID" in env
    statements = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert any("sqs:SendMessage" in s["Action"] for s in statements)
