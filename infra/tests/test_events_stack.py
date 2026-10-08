import json
import re
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from config import load
from stacks import events_stack
from stacks.data_stack import DataStack
from stacks.events_stack import EventsStack

ENVS = {"dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")
BACKEND_EVENTS = Path(__file__).resolve().parents[2] / "backend" / "found_core" / "events.py"


def template() -> Template:
    # Skip bundling so tests do not install packages.
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    return Template.from_stack(EventsStack(app, "Events", cfg=cfg, table=data.table, env=ENV))


def pipe(t: Template) -> dict:
    return next(iter(t.find_resources("AWS::Pipes::Pipe").values()))


def test_bus_is_named_per_environment():
    template().has_resource_properties("AWS::Events::EventBus", {"Name": "found-events-dev"})


def test_pipe_reads_table_stream_and_targets_bus():
    t = template()
    props = pipe(t)["Properties"]
    assert "StreamArn" in json.dumps(props["Source"])
    bus_id = next(iter(t.find_resources("AWS::Events::EventBus")))
    assert props["Target"] == {"Fn::GetAtt": [bus_id, "Arn"]}
    params = props["TargetParameters"]["EventBridgeEventBusParameters"]
    assert params == {"Source": "found.ddb", "DetailType": "found.ddb.change"}


def test_pipe_retries_bisects_and_dead_letters():
    stream = pipe(template())["Properties"]["SourceParameters"]["DynamoDBStreamParameters"]
    assert stream["StartingPosition"] == "LATEST"
    assert stream["MaximumRetryAttempts"] == 10
    assert stream["MaximumRecordAgeInSeconds"] == 3600
    assert stream["OnPartialBatchItemFailure"] == "AUTOMATIC_BISECT"
    assert "PipeDlq" in json.dumps(stream["DeadLetterConfig"])


def test_dlq_keeps_messages_for_two_weeks():
    template().has_resource_properties(
        "AWS::SQS::Queue",
        {"QueueName": "found-dev-pipe-dlq", "MessageRetentionPeriod": 14 * 24 * 3600},
    )


def test_pipe_role_can_read_stream_put_events_and_dead_letter():
    t = template()
    actions = {
        a
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    }
    stream_read = {"dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:DescribeStream"}
    assert stream_read <= actions
    assert {"events:PutEvents", "sqs:SendMessage"} <= actions
    t.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Principal": {"Service": "pipes.amazonaws.com"},
                            "Condition": {"StringEquals": {"aws:SourceAccount": "111111111111"}},
                        }
                    )
                ]
            }
        },
    )


def test_pipe_waits_for_its_role_policy():
    t = template()
    policy_ids = set(t.find_resources("AWS::IAM::Policy"))
    assert policy_ids & set(pipe(t).get("DependsOn", []))


def _matches(pattern, value) -> bool:
    """Equality subset of EventBridge pattern matching, enough for the Pipe filters."""
    if isinstance(pattern, dict):
        return isinstance(value, dict) and all(
            k in value and _matches(v, value[k]) for k, v in pattern.items()
        )
    return value in pattern


def _record(event_name: str, entity_type: str) -> dict:
    return {
        "eventName": event_name,
        "dynamodb": {"NewImage": {"entity_type": {"S": entity_type}, "PK": {"S": "x"}}},
    }


@pytest.mark.parametrize(
    ("event_name", "entity", "forwarded"),
    [
        ("INSERT", "CLAIM", True),
        ("INSERT", "SUBJECT", True),
        ("INSERT", "ALERT", True),
        ("MODIFY", "INVESTIGATION", True),
        ("MODIFY", "SUBJECT", False),
        ("INSERT", "IDEM", False),
        ("INSERT", "NAME_TOKEN", False),
        ("INSERT", "MENTION", False),
        ("REMOVE", "CLAIM", False),
    ],
)
def test_pipe_filter_forwards_only_what_consumers_need(event_name, entity, forwarded):
    record = _record(event_name, entity)
    patterns = [json.loads(p) for p in events_stack.PIPE_FILTERS]
    assert any(_matches(p, record) for p in patterns) is forwarded
    stored = pipe(template())["Properties"]["SourceParameters"]["FilterCriteria"]["Filters"]
    assert [f["Pattern"] for f in stored] == list(events_stack.PIPE_FILTERS)


def test_event_names_match_backend():
    source = BACKEND_EVENTS.read_text(encoding="utf-8")
    assert re.search(rf'EVENT_SOURCE = "{events_stack.EVENT_SOURCE}"', source)
    assert re.search(rf'EVENT_DETAIL_TYPE = "{events_stack.EVENT_DETAIL_TYPE}"', source)


def test_stack_exports_bus_and_dlq():
    assert {"EventBusName", "PipeDlqUrl"} <= set(template().find_outputs("*"))


def test_watcher_function_settings():
    template().has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "found-dev-watcher",
            "Handler": "handlers.watcher.handler",
            "Runtime": "python3.12",
            "Architectures": ["arm64"],
            "TracingConfig": {"Mode": "Active"},
            "Environment": {"Variables": Match.object_like({"TABLE_NAME": Match.any_value()})},
            "DeadLetterConfig": {"TargetArn": Match.any_value()},
        },
    )


def test_watcher_function_retries_twice_within_an_hour():
    template().has_resource_properties(
        "AWS::Lambda::EventInvokeConfig",
        {"MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 3600},
    )


def test_claim_inserted_rule_targets_watcher_with_retries_and_dlq():
    t = template()
    rules = t.find_resources(
        "AWS::Events::Rule", {"Properties": {"Name": "found-dev-claim-inserted"}}
    )
    (rule,) = rules.values()
    props = rule["Properties"]
    assert props["EventPattern"] == {
        "source": ["found.ddb"],
        "detail-type": ["found.ddb.change"],
        "detail": {
            "eventName": ["INSERT"],
            "dynamodb": {"NewImage": {"entity_type": {"S": ["CLAIM"]}}},
        },
    }
    (target,) = props["Targets"]
    assert target["RetryPolicy"] == {"MaximumRetryAttempts": 5, "MaximumEventAgeInSeconds": 3600}
    assert "WatcherDlq" in json.dumps(target["DeadLetterConfig"])
    assert "WatcherFunction" in json.dumps(target["Arn"])
    assert "Bus" in json.dumps(props["EventBusName"])


def test_watcher_dlq_accepts_failed_rule_deliveries():
    t = template()
    t.has_resource_properties("AWS::SQS::Queue", {"QueueName": "found-dev-watcher-dlq"})
    policies = t.find_resources("AWS::SQS::QueuePolicy")
    statements = [
        s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert any(
        s.get("Principal") == {"Service": "events.amazonaws.com"}
        and s["Action"] == "sqs:SendMessage"
        for s in statements
    )


def test_watcher_can_query_and_write_the_table():
    t = template()
    actions = {
        a
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
    }
    assert {"dynamodb:Query", "dynamodb:PutItem", "dynamodb:GetItem"} <= actions
