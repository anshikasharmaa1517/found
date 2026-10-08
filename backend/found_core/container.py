"""Builds services once per cold start. Settings come from the Lambda environment."""

import os
from functools import cache
from typing import TYPE_CHECKING

from found_core.adapters.cognito_jwt import CognitoTokenVerifier
from found_core.domain.cursor import CursorCodec
from found_core.ports.repository import FoundRepository
from found_core.services.ingest import IngestService
from found_core.services.people import PeopleService
from found_core.services.realtime import ConnectionService, PushService
from found_core.services.reports import ReportService
from found_core.services.subscriptions import SubscriptionService
from found_core.services.watch import WatchService

if TYPE_CHECKING:
    from found_core.adapters.apigw_connections import ApiGatewayConnections


@cache
def repository() -> FoundRepository:
    import boto3

    from found_core.adapters.dynamodb import DynamoFoundRepository

    return DynamoFoundRepository(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))


@cache
def cursor_codec() -> CursorCodec:
    import boto3

    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["CURSOR_SECRET_ARN"]
    )
    return CursorCodec(secret["SecretString"].encode())


@cache
def report_service() -> ReportService:
    repo = repository()
    return ReportService(repo, IngestService(repo))


@cache
def people_service() -> PeopleService:
    return PeopleService(repository(), cursor_codec())


@cache
def watch_service() -> WatchService:
    return WatchService(repository())


@cache
def subscription_service() -> SubscriptionService:
    return SubscriptionService(repository(), cursor_codec())


@cache
def connection_gateway() -> "ApiGatewayConnections":
    import boto3

    from found_core.adapters.apigw_connections import ApiGatewayConnections

    client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["WS_ENDPOINT"])
    return ApiGatewayConnections(client)


@cache
def connection_service() -> ConnectionService:
    return ConnectionService(repository(), connection_gateway())


@cache
def push_service() -> PushService:
    return PushService(repository(), connection_gateway())


@cache
def token_verifier() -> CognitoTokenVerifier:
    return CognitoTokenVerifier(
        os.environ["AWS_REGION"], os.environ["USER_POOL_ID"], os.environ["USER_POOL_CLIENT_ID"]
    )
