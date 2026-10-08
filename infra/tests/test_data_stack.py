import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from config import load
from stacks.data_stack import DataStack

ENVS = {
    "dev": {"deletion_protection": False, "web_origins": ["http://localhost:5173"]},
    "demo": {"deletion_protection": True, "web_origins": ["https://demo.example.org"]},
}


def template(env_name: str) -> Template:
    app = cdk.App()
    stack = DataStack(
        app,
        "Data",
        cfg=load(env_name, ENVS),
        env=cdk.Environment(account="111111111111", region="ap-south-1"),
    )
    return Template.from_stack(stack)


def test_table_matches_physical_design():
    t = template("demo")
    t.resource_count_is("AWS::DynamoDB::GlobalTable", 1)
    t.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "found-main-demo",
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "StreamSpecification": {"StreamViewType": "NEW_AND_OLD_IMAGES"},
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
            "Replicas": [
                Match.object_like(
                    {
                        "DeletionProtectionEnabled": True,
                        "PointInTimeRecoverySpecification": {
                            "PointInTimeRecoveryEnabled": True
                        },
                    }
                )
            ],
        },
    )


def test_table_has_three_overloaded_indexes_with_all_projection():
    t = template("dev")
    props = next(iter(t.find_resources("AWS::DynamoDB::GlobalTable").values()))["Properties"]
    indexes = {i["IndexName"]: i for i in props["GlobalSecondaryIndexes"]}
    assert sorted(indexes) == ["GSI1", "GSI2", "GSI3"]
    for name, index in indexes.items():
        assert index["KeySchema"] == [
            {"AttributeName": f"{name}PK", "KeyType": "HASH"},
            {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
        ]
        assert index["Projection"] == {"ProjectionType": "ALL"}
    assert {a["AttributeType"] for a in props["AttributeDefinitions"]} == {"S"}


@pytest.mark.parametrize(
    ("env_name", "policy", "protected"), [("dev", "Delete", False), ("demo", "Retain", True)]
)
def test_table_protection_follows_environment(env_name, policy, protected):
    tables = template(env_name).find_resources("AWS::DynamoDB::GlobalTable")
    table = next(iter(tables.values()))
    assert table["DeletionPolicy"] == policy
    assert table["Properties"]["Replicas"][0]["DeletionProtectionEnabled"] is protected


def test_bucket_is_private_versioned_encrypted_and_emits_events():
    t = template("demo")
    t.has_resource(
        "AWS::S3::Bucket",
        {
            "DeletionPolicy": "Retain",
            "Properties": Match.object_like(
                {
                    "VersioningConfiguration": {"Status": "Enabled"},
                    "BucketEncryption": {
                        "ServerSideEncryptionConfiguration": [
                            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                        ]
                    },
                    "PublicAccessBlockConfiguration": {
                        "BlockPublicAcls": True,
                        "BlockPublicPolicy": True,
                        "IgnorePublicAcls": True,
                        "RestrictPublicBuckets": True,
                    },
                    "NotificationConfiguration": {
                        "EventBridgeConfiguration": {"EventBridgeEnabled": True}
                    },
                    "CorsConfiguration": {
                        "CorsRules": [
                            Match.object_like(
                                {"AllowedOrigins": ["https://demo.example.org"]}
                            )
                        ]
                    },
                }
            ),
        },
    )


def test_bucket_rejects_plain_http():
    t = template("dev")
    t.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_bucket_events_need_no_custom_resource():
    t = template("dev")
    t.resource_count_is("Custom::S3BucketNotifications", 0)
    t.resource_count_is("AWS::Lambda::Function", 0)


def test_stack_exports_table_stream_and_bucket():
    outputs = template("dev").find_outputs("*")
    assert {"TableName", "TableStreamArn", "BucketName"} <= set(outputs)


def test_unknown_environment_is_rejected():
    with pytest.raises(ValueError):
        load("prod", ENVS)
