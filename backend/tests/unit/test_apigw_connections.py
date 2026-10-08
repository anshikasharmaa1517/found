import boto3
import pytest
from botocore.stub import Stubber

from found_core.adapters.apigw_connections import ApiGatewayConnections


@pytest.fixture
def stubbed():
    client = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url="https://abc.execute-api.ap-south-1.amazonaws.com/prod",
        region_name="ap-south-1",
        aws_access_key_id="x",
        aws_secret_access_key="x",
    )
    with Stubber(client) as stub:
        yield ApiGatewayConnections(client), stub


def test_send_posts_the_data(stubbed):
    gateway, stub = stubbed
    stub.add_response("post_to_connection", {}, {"ConnectionId": "c1", "Data": b"{}"})
    assert gateway.send("c1", b"{}") is True


def test_send_reports_gone_connections(stubbed):
    gateway, stub = stubbed
    stub.add_client_error("post_to_connection", service_error_code="GoneException")
    assert gateway.send("c1", b"{}") is False


def test_send_raises_other_errors(stubbed):
    gateway, stub = stubbed
    stub.add_client_error("post_to_connection", service_error_code="LimitExceededException")
    with pytest.raises(Exception, match="LimitExceeded"):
        gateway.send("c1", b"{}")


def test_close_ignores_gone(stubbed):
    gateway, stub = stubbed
    stub.add_client_error("delete_connection", service_error_code="GoneException")
    stub.add_response("delete_connection", {}, {"ConnectionId": "c2"})
    gateway.close("c1")
    gateway.close("c2")
