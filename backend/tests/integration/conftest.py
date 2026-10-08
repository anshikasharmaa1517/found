import boto3
import pytest
from moto import mock_aws

from found_core.adapters.dynamodb import DynamoFoundRepository, incident_key

TABLE = "found-main"


def create_table(resource):
    attrs = ["PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "GSI3PK", "GSI3SK"]
    return resource.create_table(
        TableName=TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in attrs],
        GlobalSecondaryIndexes=[
            {
                "IndexName": f"GSI{n}",
                "KeySchema": [
                    {"AttributeName": f"GSI{n}PK", "KeyType": "HASH"},
                    {"AttributeName": f"GSI{n}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for n in (1, 2, 3)
        ],
    )


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        yield create_table(boto3.resource("dynamodb", region_name="ap-south-1"))


@pytest.fixture
def repo(table):
    table.put_item(Item={**incident_key("inc_1"), "entity_type": "INCIDENT"})
    return DynamoFoundRepository(table)
