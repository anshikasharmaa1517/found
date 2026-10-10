import json

import aws_cdk as cdk
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.assertions import Template

from config import load
from stacks.data_stack import DataStack
from stacks.intake_stack import IntakeStack

ENVS = {"dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template(with_key: bool = True) -> Template:
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    secrets = cdk.Stack(app, "Secrets", env=ENV)
    key = secretsmanager.Secret(secrets, "Key") if with_key else None
    stack = IntakeStack(
        app,
        "Intake",
        cfg=cfg,
        table=data.table,
        bucket=data.bucket,
        model_id="model-x",
        api_key_secret=key,
        env=ENV,
    )
    return Template.from_stack(stack)


def definition(t: Template) -> dict:
    (machine,) = t.find_resources("AWS::StepFunctions::StateMachine").values()
    body = machine["Properties"]["DefinitionString"]
    # The definition is a Fn::Join of strings and tokens; keep the strings.
    text = "".join(p if isinstance(p, str) else "TOKEN" for p in body["Fn::Join"][1])
    return json.loads(text)


def test_workflow_validates_extracts_and_stores_with_failures_recorded():
    states = definition(template())["States"]
    assert definition(template())["StartAt"] == "ValidateObject"
    assert states["ValidateObject"]["Next"] == "IsNewJob"
    choice = states["IsNewJob"]
    assert choice["Choices"][0]["Next"] == "AlreadyStarted"
    assert choice["Default"] == "ExtractCandidates"
    assert states["ExtractCandidates"]["Next"] == "StoreCandidates"
    for name in ("ValidateObject", "ExtractCandidates", "StoreCandidates"):
        (catch,) = states[name]["Catch"]
        assert catch == {
            "ErrorEquals": ["States.ALL"],
            "ResultPath": "$.error",
            "Next": "MarkFailed",
        }
    assert states["MarkFailed"]["Next"] == "IntakeFailed"
    assert states["IntakeFailed"]["Type"] == "Fail"


def test_extraction_retries_transient_errors_only():
    states = definition(template())["States"]
    retries = states["ExtractCandidates"]["Retry"]
    ours = next(r for r in retries if "ClientError" in r["ErrorEquals"])
    assert ours["MaxAttempts"] == 3 and ours["BackoffRate"] == 2
    assert all("ExtractionFailed" not in r["ErrorEquals"] for r in retries)


def test_each_step_names_itself_to_the_function():
    states = definition(template())["States"]
    steps = {
        name: states[name]["Parameters"]["step"]
        for name in ("ValidateObject", "ExtractCandidates", "StoreCandidates", "MarkFailed")
    }
    assert steps == {
        "ValidateObject": "validate",
        "ExtractCandidates": "extract",
        "StoreCandidates": "store",
        "MarkFailed": "fail",
    }


def test_only_intake_objects_in_the_data_bucket_start_it():
    t = template()
    (rule,) = t.find_resources("AWS::Events::Rule").values()
    pattern = rule["Properties"]["EventPattern"]
    assert pattern["source"] == ["aws.s3"] and pattern["detail-type"] == ["Object Created"]
    assert pattern["detail"]["object"] == {"key": [{"prefix": "intake/"}]}
    assert "StepFunctions" in json.dumps(rule["Properties"]["Targets"]) or "IntakeWorkflow" in (
        json.dumps(rule["Properties"]["Targets"])
    )


def _statements(t: Template) -> list[dict]:
    return [
        s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]


def _actions(s: dict) -> list[str]:
    return s["Action"] if isinstance(s["Action"], list) else [s["Action"]]


def test_function_reads_intake_objects_textract_and_the_key():
    t = template()
    fn = next(iter(t.find_resources("AWS::Lambda::Function").values()))["Properties"]
    env = fn["Environment"]["Variables"]
    assert env["MODEL_ID"] == "model-x" and "BEDROCK_API_KEY_SECRET_ARN" in env
    assert fn["Timeout"] == 90
    statements = _statements(t)
    reads = [s for s in statements if "s3:GetObject*" in _actions(s)]
    assert reads and all("/intake/*" in json.dumps(s["Resource"]) for s in reads)
    assert any("textract:DetectDocumentText" in _actions(s) for s in statements)
    assert any("secretsmanager:GetSecretValue" in _actions(s) for s in statements)
    assert not any("bedrock:InvokeModel" in _actions(s) for s in statements)


def test_without_a_key_the_function_may_call_only_its_model():
    t = template(with_key=False)
    (invoke,) = [s for s in _statements(t) if "bedrock:InvokeModel" in _actions(s)]
    assert all("model-x" in json.dumps(r) for r in invoke["Resource"])
