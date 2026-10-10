"""Table stream to EventBridge Pipe to the `found-events` bus (design Section 12.2).

The Pipe is the only stream reader. It forwards only the changes some consumer needs,
and consumers subscribe with rules on the bus, so adding one never touches the stream.
Each consumer is a Lambda with its own rule and dead-letter queue (design Section 12.2).
"""

import json

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_pipes as pipes
from aws_cdk import aws_ses as ses
from constructs import Construct

from config import EnvConfig
from stacks.consumer import (
    EVENT_DETAIL_TYPE,
    EVENT_SOURCE,
    MAX_EVENT_AGE,
    dead_letter_queue,
    event_consumer,
    inserted,
    released_alert,
)

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


# Alerts change status several times; only a release (back to PENDING) is forwarded.
RELEASED_ALERT_FILTER = json.dumps(
    {
        "eventName": ["MODIFY"],
        "dynamodb": {
            "NewImage": {"entity_type": {"S": ["ALERT"]}, "delivery_status": {"S": ["PENDING"]}}
        },
    },
    separators=(",", ":"),
)

PIPE_FILTERS = (
    _entity_filter("INSERT", INSERTED_ENTITIES),
    _entity_filter("MODIFY", MODIFIED_ENTITIES),
    RELEASED_ALERT_FILTER,
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

        self.watcher = event_consumer(
            self,
            "Watcher",
            env_name=cfg.name,
            retention=cfg.retention,
            handler="handlers.watcher.handler",
            rules=[("claim-inserted", inserted("CLAIM"))],
            bus=self.bus,
            table=table,
        )

        # Proposes possible same-person pairs for each new person record (design 6.3).
        self.resolver = event_consumer(
            self,
            "Resolver",
            env_name=cfg.name,
            retention=cfg.retention,
            handler="handlers.resolver.handler",
            rules=[("person-inserted", inserted("SUBJECT", subject_type="PERSON"))],
            bus=self.bus,
            table=table,
        )

        # Sends due alerts by email or text (design 6.4). Held alerts arrive on release.
        self.notifier = event_consumer(
            self,
            "Notifier",
            env_name=cfg.name,
            retention=cfg.retention,
            handler="handlers.notifier.handler",
            rules=[
                ("alert-inserted", inserted("ALERT", delivery_status="PENDING")),
                ("alert-released", released_alert()),
            ],
            bus=self.bus,
            table=table,
            environment={
                "EMAIL_FROM": cfg.email_from,
                "SMS_ENABLED": "true" if cfg.sms_enabled else "false",
            },
        )
        if cfg.email_from:
            # Creating the identity mails a verification link to the sender address.
            sender = ses.EmailIdentity(
                self, "AlertSender", identity=ses.Identity.email(cfg.email_from)
            )
            self.notifier.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ses:SendEmail"],
                    resources=[
                        self.format_arn(
                            service="ses",
                            resource="identity",
                            resource_name=sender.email_identity_name,
                        )
                    ],
                )
            )
        if cfg.sms_enabled:
            # Text messages go to phone numbers, which have no ARN to scope to.
            self.notifier.add_to_role_policy(
                iam.PolicyStatement(actions=["sns:Publish"], resources=["*"])
            )

        cdk.CfnOutput(self, "EventBusName", value=self.bus.event_bus_name)
        cdk.CfnOutput(self, "PipeDlqUrl", value=self.pipe_dlq.queue_url)
