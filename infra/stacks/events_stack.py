"""Table stream to EventBridge Pipe to the `found-events` bus (design Section 12.2).

The Pipe is the only stream reader. It forwards only the changes some consumer needs,
and consumers subscribe with rules on the bus, so adding one never touches the stream.
Each consumer is a Lambda with its own rule and dead-letter queue (design Section 12.2).
"""

import json

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_pipes as pipes
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from config import EnvConfig
from stacks.lambda_code import backend_code

# Must match `found_core.events`. Rules match on these two fields.
EVENT_SOURCE = "found.ddb"
EVENT_DETAIL_TYPE = "found.ddb.change"

# Retries end after one hour, then the record or event goes to a dead-letter queue.
MAX_EVENT_AGE = cdk.Duration.hours(1)
TARGET_RETRIES = 5
DLQ_RETENTION = cdk.Duration.days(14)

# Subjects are stored as SUBJECT with a `subject_type`; the resolver rule narrows to people.
INSERTED_ENTITIES = ["CLAIM", "SUBJECT", "ALERT", "INVESTIGATION_STEP", "REVIEW_ITEM"]
MODIFIED_ENTITIES = ["INVESTIGATION"]


def _entity_filter(event_name: str, entities: list[str]) -> str:
    return json.dumps(
        {
            "eventName": [event_name],
            "dynamodb": {"NewImage": {"entity_type": {"S": entities}}},
        },
        separators=(",", ":"),
    )


PIPE_FILTERS = (
    _entity_filter("INSERT", INSERTED_ENTITIES),
    _entity_filter("MODIFY", MODIFIED_ENTITIES),
)


def inserted(entity_type: str) -> events.EventPattern:
    return events.EventPattern(
        source=[EVENT_SOURCE],
        detail_type=[EVENT_DETAIL_TYPE],
        detail={
            "eventName": ["INSERT"],
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

class EventsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bus = events.EventBus(self, "Bus", event_bus_name=f"found-events-{cfg.name}")

        # Records the Pipe could not deliver after its retries land here for inspection.
        self.pipe_dlq = dead_letter_queue(self, "PipeDlq", f"found-{cfg.name}-pipe-dlq")

        role = iam.Role(
            self,
            "PipeRole",
            assumed_by=iam.ServicePrincipal(
                "pipes.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        table.grant_stream_read(role)
        self.bus.grant_put_events_to(role)
        self.pipe_dlq.grant_send_messages(role)

        self.pipe = pipes.CfnPipe(
            self,
            "TablePipe",
            name=f"found-{cfg.name}-ddb-pipe",
            role_arn=role.role_arn,
            source=table.table_stream_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                dynamo_db_stream_parameters=pipes.CfnPipe.PipeSourceDynamoDBStreamParametersProperty(
                    starting_position="LATEST",
                    batch_size=10,
                    maximum_batching_window_in_seconds=1,
                    maximum_retry_attempts=10,
                    maximum_record_age_in_seconds=int(MAX_EVENT_AGE.to_seconds()),
                    on_partial_batch_item_failure="AUTOMATIC_BISECT",
                    dead_letter_config=pipes.CfnPipe.DeadLetterConfigProperty(
                        arn=self.pipe_dlq.queue_arn
                    ),
                ),
                filter_criteria=pipes.CfnPipe.FilterCriteriaProperty(
                    filters=[pipes.CfnPipe.FilterProperty(pattern=p) for p in PIPE_FILTERS]
                ),
            ),
            target=self.bus.event_bus_arn,
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                event_bridge_event_bus_parameters=pipes.CfnPipe.PipeTargetEventBridgeEventBusParametersProperty(
                    source=EVENT_SOURCE, detail_type=EVENT_DETAIL_TYPE
                )
            ),
        )
        # The Pipe validates its permissions on create, so the policy must exist first.
        self.pipe.node.add_dependency(role)

        # Watcher: one rule, retries, then its own dead-letter queue (design Section 10.4).
        watcher_dlq = dead_letter_queue(self, "WatcherDlq", f"found-{cfg.name}-watcher-dlq")
        self.watcher = lambda_.Function(
            self,
            "WatcherFunction",
            function_name=f"found-{cfg.name}-watcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.watcher.handler",
            code=backend_code(),
            memory_size=256,
            timeout=cdk.Duration.seconds(30),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                "POWERTOOLS_SERVICE_NAME": "watcher",
                "LOG_LEVEL": "INFO",
            },
            retry_attempts=2,
            max_event_age=MAX_EVENT_AGE,
            dead_letter_queue=watcher_dlq,
            log_group=logs.LogGroup(
                self,
                "WatcherLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.watcher)
        events.Rule(
            self,
            "ClaimInsertedRule",
            rule_name=f"found-{cfg.name}-claim-inserted",
            event_bus=self.bus,
            event_pattern=inserted("CLAIM"),
            targets=[
                targets.LambdaFunction(
                    self.watcher,
                    retry_attempts=TARGET_RETRIES,
                    max_event_age=MAX_EVENT_AGE,
                    dead_letter_queue=watcher_dlq,
                )
            ],
        )

        cdk.CfnOutput(self, "EventBusName", value=self.bus.event_bus_name)
        cdk.CfnOutput(self, "PipeDlqUrl", value=self.pipe_dlq.queue_url)
