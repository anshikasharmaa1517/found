import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from config import load
from stacks.observability_stack import DLQS, ERROR_ALARMS, ObservabilityStack

BASE = {"deletion_protection": False, "web_origins": ["http://localhost:5173"]}
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def template(**settings) -> Template:
    app = cdk.App()
    cfg = load("dev", {"dev": {**BASE, **settings}})
    return Template.from_stack(ObservabilityStack(app, "Obs", cfg=cfg, env=ENV))


def alarms(t: Template) -> dict[str, dict]:
    return {
        a["Properties"]["AlarmName"]: a["Properties"]
        for a in t.find_resources("AWS::CloudWatch::Alarm").values()
    }


def test_every_dead_letter_queue_has_an_alarm_on_its_first_message():
    found = alarms(template())
    for queue in DLQS:
        props = found[f"found-dev-dlq-{queue}"]
        assert props["Namespace"] == "AWS/SQS" and props["Threshold"] == 1
        assert props["Dimensions"] == [{"Name": "QueueName", "Value": f"found-dev-{queue}-dlq"}]
        assert props["TreatMissingData"] == "notBreaching"


def test_errors_and_failed_intake_runs_alarm():
    found = alarms(template())
    for function, threshold in ERROR_ALARMS.items():
        props = found[f"found-dev-errors-{function}"]
        assert props["MetricName"] == "Errors" and props["Threshold"] == threshold
        assert props["Dimensions"] == [{"Name": "FunctionName", "Value": f"found-dev-{function}"}]
    intake = found["found-dev-intakefailed"]
    assert intake["Namespace"] == "AWS/States" and intake["MetricName"] == "ExecutionsFailed"
    assert "stateMachine:found-dev-intake" in json.dumps(intake["Dimensions"])
    # Kept small on purpose: each alarm is billed monthly.
    assert len(found) == len(DLQS) + len(ERROR_ALARMS) + 1


def test_alarms_notify_the_topic_both_ways():
    t = template()
    for props in alarms(t).values():
        assert props["AlarmActions"] and props["OKActions"]
        assert "AlarmTopic" in json.dumps(props["AlarmActions"])


def test_the_alarm_email_is_subscribed_only_when_set():
    template().resource_count_is("AWS::SNS::Subscription", 0)
    t = template(alarm_email="ops@example.org")
    t.has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "ops@example.org"}
    )


def test_one_dashboard_shows_the_alarms():
    t = template()
    (dashboard,) = t.find_resources("AWS::CloudWatch::Dashboard").values()
    assert dashboard["Properties"]["DashboardName"] == "found-dev"
    body = json.dumps(dashboard["Properties"]["DashboardBody"])
    assert "Dead-letter queues" in body and "Intake runs" in body and "alarm" in body


def test_a_budget_is_created_only_when_asked_for():
    template().resource_count_is("AWS::Budgets::Budget", 0)
    t = template(budget_usd=30, alarm_email="ops@example.org")
    (budget,) = t.find_resources("AWS::Budgets::Budget").values()
    props = budget["Properties"]
    assert props["Budget"]["BudgetLimit"] == {"Amount": 30, "Unit": "USD"}
    thresholds = [n["Notification"]["Threshold"] for n in props["NotificationsWithSubscribers"]]
    assert thresholds == [50, 80, 100]
