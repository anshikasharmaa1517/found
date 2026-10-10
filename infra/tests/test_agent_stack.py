import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from config import load
from stacks.agent_stack import MAX_TOOL_CALLS, AgentStack, load_tool_specs
from stacks.data_stack import DataStack

ENVS = {"dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template() -> Template:
    # Skip bundling so tests do not install packages.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    return Template.from_stack(AgentStack(app, "Agent", cfg=cfg, table=data.table, env=ENV))


def one(t: Template, kind: str) -> dict:
    found = t.find_resources(kind)
    assert len(found) == 1, kind
    return next(iter(found.values()))["Properties"]


def test_model_is_a_deploy_parameter():
    params = template().to_json()["Parameters"]
    assert params["ModelId"]["Type"] == "String"
    assert params["ModelId"]["MinLength"] == 1


def test_run_queue_retries_twice_then_dead_letters():
    t = template()
    t.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "found-dev-investigation-queue",
            "VisibilityTimeout": 300,
            "RedrivePolicy": {"maxReceiveCount": 2, "deadLetterTargetArn": Match.any_value()},
        },
    )
    t.has_resource_properties(
        "AWS::SQS::Queue",
        {"QueueName": "found-dev-investigation-dlq", "MessageRetentionPeriod": 14 * 24 * 3600},
    )


def test_tools_lambda_reads_the_table_and_knows_the_model():
    t = template()
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "found-dev-agent-tools",
            "Handler": "handlers.agent_tools.handler",
            "Architectures": ["arm64"],
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "MODEL_ID": {"Ref": "ModelId"},
                        "MAX_TOOL_CALLS": str(MAX_TOOL_CALLS),
                        "TABLE_NAME": Match.any_value(),
                    }
                )
            },
        },
    )


def test_gateway_uses_iam_auth_and_mcp():
    props = one(template(), "AWS::BedrockAgentCore::Gateway")
    assert props["AuthorizerType"] == "AWS_IAM"
    assert props["ProtocolType"] == "MCP"


def test_gateway_target_publishes_every_tool_with_its_role():
    props = one(template(), "AWS::BedrockAgentCore::GatewayTarget")
    assert props["CredentialProviderConfigurations"] == [
        {"CredentialProviderType": "GATEWAY_IAM_ROLE"}
    ]
    lambda_target = props["TargetConfiguration"]["Mcp"]["Lambda"]
    tools = lambda_target["ToolSchema"]["InlinePayload"]
    specs = load_tool_specs()
    assert [tool["Name"] for tool in tools] == [s["name"] for s in specs]
    finding = next(tool for tool in tools if tool["Name"] == "record_finding")
    schema = finding["InputSchema"]
    assert schema["Type"] == "object"
    assert set(schema["Required"]) >= {"attribution", "comparison", "summary", "citations"}
    # Property names are tool argument names and keep their case.
    assert list(schema["Properties"]) == list(specs[-1]["inputSchema"]["properties"])
    assert schema["Properties"]["citations"]["Items"]["Required"] == ["claim_id", "excerpt"]


def test_guardrail_filters_prompt_attacks_on_input():
    props = one(template(), "AWS::Bedrock::Guardrail")
    assert props["ContentPolicyConfig"]["FiltersConfig"] == [
        {"Type": "PROMPT_ATTACK", "InputStrength": "HIGH", "OutputStrength": "NONE"}
    ]


def test_runtime_runs_the_agent_zip_with_gateway_and_guardrail():
    props = one(template(), "AWS::BedrockAgentCore::Runtime")
    code = props["AgentRuntimeArtifact"]["CodeConfiguration"]
    assert code["EntryPoint"] == ["main.py"] and code["Runtime"] == "PYTHON_3_12"
    assert set(code["Code"]["S3"]) == {"Bucket", "Prefix"}
    env = props["EnvironmentVariables"]
    assert env["MODEL_ID"] == {"Ref": "ModelId"}
    assert set(env) == {"MODEL_ID", "GATEWAY_URL", "GUARDRAIL_ID", "GUARDRAIL_VERSION"}
    assert props["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}


def _statements(t: Template) -> list[dict]:
    return [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]


def _actions(statement: dict) -> set[str]:
    action = statement["Action"]
    return set(action if isinstance(action, list) else [action])


def test_runtime_role_may_call_the_model_guardrail_and_gateway_only():
    t = template()
    actions = set().union(*(_actions(s) for s in _statements(t)))
    assert {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"} <= actions
    assert {"bedrock:ApplyGuardrail", "bedrock-agentcore:InvokeGateway"} <= actions
    gateway = next(s for s in _statements(t) if "bedrock-agentcore:InvokeGateway" in _actions(s))
    assert "GatewayArn" in json.dumps(gateway["Resource"])
    roles = t.find_resources("AWS::IAM::Role")
    principals = {
        json.dumps(r["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"])
        for r in roles.values()
    }
    assert json.dumps({"Service": "bedrock-agentcore.amazonaws.com"}) in principals


def test_gateway_role_can_invoke_the_tools_lambda():
    t = template()
    invoke = [s for s in _statements(t) if "lambda:InvokeFunction" in _actions(s)]
    assert invoke and "ToolsFunction" in json.dumps(invoke)


def test_runner_reads_the_queue_two_at_a_time_without_reserved_concurrency():
    t = template()
    t.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 1,
            "ScalingConfig": {"MaximumConcurrency": 2},
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )
    runner = next(
        r["Properties"]
        for r in t.find_resources("AWS::Lambda::Function").values()
        if r["Properties"].get("FunctionName") == "found-dev-investigation-runner"
    )
    assert "ReservedConcurrentExecutions" not in runner
    assert runner["Handler"] == "handlers.investigation_runner.handler"
    assert runner["Timeout"] == 180
    env = runner["Environment"]["Variables"]
    assert env["MODEL_ID"] == {"Ref": "ModelId"} and "RUNTIME_ARN" in env


def test_queue_hides_a_message_longer_than_a_run_takes():
    props = next(
        q["Properties"]
        for q in template().find_resources("AWS::SQS::Queue").values()
        if q["Properties"].get("QueueName") == "found-dev-investigation-queue"
    )
    assert props["VisibilityTimeout"] > 180


def test_runner_may_invoke_only_the_agent_runtime():
    statements = [
        s for s in _statements(template()) if "bedrock-agentcore:InvokeAgentRuntime" in _actions(s)
    ]
    assert len(statements) == 1
    assert "AgentRuntimeArn" in json.dumps(statements[0]["Resource"])


def lambda_host_template() -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    envs = {"dev": {**ENVS["dev"], "agent_host": "lambda"}}
    cfg = load("dev", envs)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    return Template.from_stack(AgentStack(app, "Agent", cfg=cfg, table=data.table, env=ENV))


def test_lambda_host_runs_the_agent_in_the_runner_without_agentcore():
    t = lambda_host_template()
    for kind in (
        "AWS::BedrockAgentCore::Runtime",
        "AWS::BedrockAgentCore::Gateway",
        "AWS::BedrockAgentCore::GatewayTarget",
    ):
        t.resource_count_is(kind, 0)
    t.resource_count_is("AWS::Lambda::LayerVersion", 1)
    t.has_resource_properties("AWS::SecretsManager::Secret", {"Name": "found-dev/bedrock-api-key"})
    runner = next(
        r["Properties"]
        for r in t.find_resources("AWS::Lambda::Function").values()
        if r["Properties"].get("FunctionName") == "found-dev-investigation-runner"
    )
    env = runner["Environment"]["Variables"]
    assert env["AGENT_HOST"] == "lambda" and "BEDROCK_API_KEY_SECRET_ARN" in env
    assert "RUNTIME_ARN" not in env and len(runner["Layers"]) == 1
    assert runner["MemorySize"] == 1024 and runner["Timeout"] == 180
    t.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {"BatchSize": 1, "ScalingConfig": {"MaximumConcurrency": 2}},
    )
    statements = [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert any("secretsmanager:GetSecretValue" in s["Action"] for s in statements)
    assert "BedrockApiKeySecretArn" in t.find_outputs("*")


def test_unknown_agent_host_is_refused():
    import pytest

    with pytest.raises(ValueError):
        load("dev", {"dev": {**ENVS["dev"], "agent_host": "laptop"}})
