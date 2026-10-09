"""Event consumers: a Lambda on bus rules with retries and one dead-letter queue.

Design Sections 10.4 and 12.2. Rules retry delivery; the function's async config retries
failures; whatever is left lands in the consumer's own DLQ for inspection.
"""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from stacks.lambda_code import backend_code

# Must match `found_core.events`. Rules match on these two fields.
EVENT_SOURCE = "found.ddb"
EVENT_DETAIL_TYPE = "found.ddb.change"

MAX_EVENT_AGE = cdk.Duration.hours(1)
TARGET_RETRIES = 5
DLQ_RETENTION = cdk.Duration.days(14)


def inserted(entity_type: str) -> events.EventPattern:
    return events.EventPattern(
        source=[EVENT_SOURCE],
        detail_type=[EVENT_DETAIL_TYPE],
        detail={
            "eventName": ["INSERT"],
            "dynamodb": {"NewImage": {"entity_type": {"S": [entity_type]}}},
        },
    )


def modified(entity_type: str) -> events.EventPattern:
    return events.EventPattern(
        source=[EVENT_SOURCE],
        detail_type=[EVENT_DETAIL_TYPE],
        detail={
            "eventName": ["MODIFY"],
            "dynamodb": {"NewImage": {"entity_type": {"S": [entity_type]}}},
        },
    )


def dead_letter_queue(scope: Construct, construct_id: str, queue_name: str) -> sqs.Queue:
    return sqs.Queue(
        scope,
        construct_id,
        queue_name=queue_name,
        retention_period=DLQ_RETENTION,
        encryption=sqs.QueueEncryption.SQS_MANAGED,
        enforce_ssl=True,
    )


def event_consumer(
    scope: Construct,
    name: str,
    *,
    env_name: str,
    handler: str,
    retention: logs.RetentionDays = logs.RetentionDays.ONE_MONTH,
    rules: list[tuple[str, events.EventPattern]],
    bus: events.IEventBus,
    table: ddb.ITableV2,
    environment: dict[str, str] | None = None,
) -> lambda_.Function:
    slug = name.lower()
    dlq = dead_letter_queue(scope, f"{name}Dlq", f"found-{env_name}-{slug}-dlq")
    function = lambda_.Function(
        scope,
        f"{name}Function",
        function_name=f"found-{env_name}-{slug}",
        runtime=lambda_.Runtime.PYTHON_3_12,
        architecture=lambda_.Architecture.ARM_64,
        handler=handler,
        code=backend_code(),
        memory_size=256,
        timeout=cdk.Duration.seconds(30),
        tracing=lambda_.Tracing.ACTIVE,
        environment={
            "TABLE_NAME": table.table_name,
            "POWERTOOLS_SERVICE_NAME": slug,
            "LOG_LEVEL": "INFO",
            **(environment or {}),
        },
        retry_attempts=2,
        max_event_age=MAX_EVENT_AGE,
        dead_letter_queue=dlq,
        log_group=logs.LogGroup(
            scope,
            f"{name}Logs",
            retention=retention,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        ),
    )
    table.grant_read_write_data(function)
    for rule_name, pattern in rules:
        events.Rule(
            scope,
            f"{name}Rule-{rule_name}",
            rule_name=f"found-{env_name}-{rule_name}",
            event_bus=bus,
            event_pattern=pattern,
            targets=[
                targets.LambdaFunction(
                    function,
                    retry_attempts=TARGET_RETRIES,
                    max_event_age=MAX_EVENT_AGE,
                    dead_letter_queue=dlq,
                )
            ],
        )
    return function
