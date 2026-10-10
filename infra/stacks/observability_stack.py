"""Dashboard, alarms and (optionally) the budget (design Sections 2.2, 4.3 and 13).

Alarms watch what a person must act on: anything in a dead-letter queue, errors in the
API, the investigation runner and the notifier, and failed intake runs. A notifier that
fails after claiming an alert (leaving it SENDING) shows up as a notifier error; we
prefer a missed text to a repeated one, so a person checks it.

Resources are named by the deterministic names the other stacks give them, so this
stack adds no cross-stack exports that could block a later deploy.
"""

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from config import EnvConfig

PERIOD = cdk.Duration.minutes(5)
# Dead-letter queues, by the name suffix each stack gives them.
DLQS = ("pipe", "watcher", "resolver", "notifier", "wspush", "investigation")
# Functions whose errors page someone, and how many in five minutes do.
ERROR_ALARMS = {"api": 5, "investigation-runner": 1, "notifier": 1}
# Functions shown on the dashboard.
CONSUMERS = ("watcher", "resolver", "notifier", "wspush")
BUDGET_THRESHOLDS = (50, 80, 100)


class ObservabilityStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = f"found-{cfg.name}"

        self.topic = sns.Topic(self, "AlarmTopic", topic_name=f"{name}-alarms")
        if cfg.alarm_email:
            # The address must confirm the subscription from the email it receives.
            self.topic.add_subscription(subs.EmailSubscription(cfg.alarm_email))
        action = cw_actions.SnsAction(self.topic)

        def function_metric(function: str, metric: str, stat: str = "Sum") -> cw.Metric:
            return cw.Metric(
                namespace="AWS/Lambda",
                metric_name=metric,
                dimensions_map={"FunctionName": f"{name}-{function}"},
                statistic=stat,
                period=PERIOD,
            )

        def queue_depth(queue: str) -> cw.Metric:
            return cw.Metric(
                namespace="AWS/SQS",
                metric_name="ApproximateNumberOfMessagesVisible",
                dimensions_map={"QueueName": f"{name}-{queue}"},
                statistic="Maximum",
                period=PERIOD,
            )

        workflow_arn = self.format_arn(
            service="states",
            resource="stateMachine",
            resource_name=f"{name}-intake",
            arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
        )

        def workflow_metric(metric: str) -> cw.Metric:
            return cw.Metric(
                namespace="AWS/States",
                metric_name=metric,
                dimensions_map={"StateMachineArn": workflow_arn},
                statistic="Sum",
                period=PERIOD,
            )

        self.alarms: list[cw.Alarm] = []

        def alarm(alarm_id: str, metric: cw.Metric, threshold: float, description: str) -> None:
            created = cw.Alarm(
                self,
                alarm_id,
                alarm_name=f"{name}-{alarm_id.lower()}",
                alarm_description=description,
                metric=metric,
                threshold=threshold,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            created.add_alarm_action(action)
            created.add_ok_action(action)
            self.alarms.append(created)

        for queue in DLQS:
            alarm(
                f"Dlq-{queue}",
                queue_depth(f"{queue}-dlq"),
                1,
                f"Messages in {name}-{queue}-dlq: events that failed every retry. "
                "Inspect them before they expire after 14 days.",
            )
        for function, threshold in ERROR_ALARMS.items():
            alarm(
                f"Errors-{function}",
                function_metric(function, "Errors"),
                threshold,
                f"{name}-{function} raised errors. Check its logs.",
            )
        alarm(
            "IntakeFailed",
            workflow_metric("ExecutionsFailed"),
            1,
            "An intake run failed outside the job's own failure handling.",
        )

        dashboard = cw.Dashboard(self, "Dashboard", dashboard_name=name)
        dashboard.add_widgets(
            cw.AlarmStatusWidget(title="Alarms", alarms=self.alarms, width=24, height=4)
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="API requests and errors",
                left=[function_metric("api", "Invocations"), function_metric("api", "Errors")],
                width=12,
            ),
            cw.GraphWidget(
                title="API duration (p95, ms)",
                left=[function_metric("api", "Duration", "p95")],
                width=12,
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Event consumer errors",
                left=[function_metric(f, "Errors") for f in CONSUMERS],
                width=12,
            ),
            cw.GraphWidget(
                title="Dead-letter queues",
                left=[queue_depth(f"{q}-dlq") for q in DLQS],
                width=12,
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Investigations",
                left=[
                    function_metric("investigation-runner", "Invocations"),
                    function_metric("investigation-runner", "Errors"),
                ],
                right=[queue_depth("investigation-queue")],
                width=12,
            ),
            cw.GraphWidget(
                title="Intake runs",
                left=[
                    workflow_metric("ExecutionsStarted"),
                    workflow_metric("ExecutionsSucceeded"),
                    workflow_metric("ExecutionsFailed"),
                ],
                width=12,
            ),
        )

        if cfg.budget_usd:
            budgets.CfnBudget(
                self,
                "Budget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name=f"{name}-monthly",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.budget_usd, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            notification_type="ACTUAL",
                            comparison_operator="GREATER_THAN",
                            threshold=threshold,
                            threshold_type="PERCENTAGE",
                        ),
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                subscription_type="EMAIL", address=cfg.alarm_email
                            )
                        ],
                    )
                    for threshold in BUDGET_THRESHOLDS
                    if cfg.alarm_email
                ],
            )

        cdk.CfnOutput(self, "AlarmTopicArn", value=self.topic.topic_arn)
        cdk.CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
            f"?region={self.region}#dashboards:name={name}",
        )
