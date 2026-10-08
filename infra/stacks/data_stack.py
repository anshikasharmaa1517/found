"""DynamoDB table `found-main` and S3 bucket `found-data` (design Sections 8.5 and 4.3)."""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_s3 as s3
from constructs import Construct

from config import EnvConfig

GSI_NAMES = ("GSI1", "GSI2", "GSI3")


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: EnvConfig, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        removal = (
            cdk.RemovalPolicy.RETAIN if cfg.deletion_protection else cdk.RemovalPolicy.DESTROY
        )

        self.table = ddb.TableV2(
            self,
            "Main",
            table_name=f"found-main-{cfg.name}",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing=ddb.Billing.on_demand(),
            dynamo_stream=ddb.StreamViewType.NEW_AND_OLD_IMAGES,
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=cfg.deletion_protection,
            encryption=ddb.TableEncryptionV2.dynamo_owned_key(),
            time_to_live_attribute="ttl",
            removal_policy=removal,
            global_secondary_indexes=[
                ddb.GlobalSecondaryIndexPropsV2(
                    index_name=name,
                    partition_key=ddb.Attribute(name=f"{name}PK", type=ddb.AttributeType.STRING),
                    sort_key=ddb.Attribute(name=f"{name}SK", type=ddb.AttributeType.STRING),
                    projection_type=ddb.ProjectionType.ALL,
                )
                for name in GSI_NAMES
            ],
        )

        # Originals are immutable evidence, so the bucket is always retained.
        self.bucket = s3.Bucket(
            self,
            "Data",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.PUT],
                    allowed_origins=list(cfg.web_origins),
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-versions",
                    noncurrent_version_expiration=cdk.Duration.days(90),
                    abort_incomplete_multipart_upload_after=cdk.Duration.days(1),
                )
            ],
        )

        # Set directly instead of `event_bridge_enabled`, which adds a custom resource Lambda.
        # Intake and media rules (design Section 12.2) match these events on the default bus.
        cfn_bucket = self.bucket.node.default_child
        cfn_bucket.add_property_override(
            "NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled", True
        )

        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "TableStreamArn", value=self.table.table_stream_arn or "")
        cdk.CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
