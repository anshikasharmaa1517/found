import boto3
import pytest
from moto import mock_aws

from found_core import container


@pytest.fixture
def secret_arn(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    container.cursor_codec.cache_clear()
    with mock_aws():
        client = boto3.client("secretsmanager")
        arn = client.create_secret(Name="cursor", SecretString="s" * 64)["ARN"]
        monkeypatch.setenv("CURSOR_SECRET_ARN", arn)
        yield arn
    container.cursor_codec.cache_clear()


def test_cursor_codec_uses_the_secret(secret_arn):
    codec = container.cursor_codec()
    token = codec.encode("scope", {"s": 1})
    assert codec.decode("scope", token) == {"s": 1}
    assert container.cursor_codec() is codec
