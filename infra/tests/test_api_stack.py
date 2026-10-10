import json

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
        bucket=data.bucket,
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
            "Environment": {"Variables": Match.object_like({"TABLE_NAME": Match.any_value()})},
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
        "GET /v1/incidents/{incident_id}/climate",
        "POST /v1/people/{person_id}/subscriptions",
        "DELETE /v1/subscriptions/{subscription_id}",
        "GET /v1/me/subscriptions",
        "GET /v1/me/alerts",
        "POST /v1/claims/{claim_id}/investigations",
        "GET /v1/investigations/{investigation_id}",
        "POST /v1/investigations/{investigation_id}/review",
        "GET /v1/incidents/{incident_id}/review-queue",
        "POST /v1/incidents/{incident_id}/review-items/{review_id}/resolve",
        "POST /v1/identity-proposals/{pair_key}/decision",
        "POST /v1/incidents/{incident_id}/uploads",
        "POST /v1/incidents/{incident_id}/intake-text",
        "GET /v1/intake-jobs/{job_id}",
        "POST /v1/intake-candidates/{candidate_id}/decision",
        "GET /v1/incidents/{incident_id}/activity",
        "POST /v1/admin/incidents/{incident_id}/reset",
        "GET /v1/admin/investigations/{investigation_id}/recording",
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


def test_demo_reset_runs_in_its_own_worker_with_the_fixtures():
    t = template()
    functions = {
        r["Properties"].get("FunctionName"): r["Properties"]
        for r in t.find_resources("AWS::Lambda::Function").values()
    }
    worker = functions["found-dev-demo-reset"]
    assert worker["Handler"] == "handlers.demo_reset.handler" and worker["Timeout"] == 300
    assert worker["Environment"]["Variables"]["FIXTURES_PREFIX"] == "fixtures/demo-v1"
    api_env = functions["found-dev-api"]["Environment"]["Variables"]
    assert {"FIXTURES_BUCKET", "FIXTURES_PREFIX", "RESET_FUNCTION_NAME"} <= set(api_env)
    statements = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert any("lambda:InvokeFunction" in s["Action"] for s in statements)
    t.resource_count_is("Custom::CDKBucketDeployment", 1)
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "RestrictPublicBuckets": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
            }
        },
    )


def test_stage_waits_for_the_routes_its_throttles_name():
    t = template()
    stage = next(iter(t.find_resources("AWS::ApiGatewayV2::Stage").values()))
    routes = set(t.find_resources("AWS::ApiGatewayV2::Route"))
    assert routes and routes <= set(stage.get("DependsOn", []))


def test_api_may_write_only_under_the_intake_prefix():
    t = template()
    fn = next(
        f["Properties"]
        for f in t.find_resources("AWS::Lambda::Function").values()
        if f["Properties"].get("Handler") == "handlers.api.handler"
    )
    assert "DATA_BUCKET" in fn["Environment"]["Variables"]
    puts = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if "s3:PutObject" in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    ]
    on_data_bucket = [s for s in puts if "Data:Exports" in json.dumps(s["Resource"])]
    assert on_data_bucket
    assert all("/intake/*" in json.dumps(s["Resource"]) for s in on_data_bucket)
