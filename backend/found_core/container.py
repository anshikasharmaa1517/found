"""Builds services once per cold start. Settings come from the Lambda environment."""

import os
from functools import cache
from typing import TYPE_CHECKING

from found_core.adapters.cognito_jwt import CognitoTokenVerifier
from found_core.domain.cursor import CursorCodec
from found_core.domain.investigation import InvestigationConfig
from found_core.ports.repository import FoundRepository
from found_core.services.climate import ClimateService
from found_core.services.demo import DemoService
from found_core.services.ingest import IngestService
from found_core.services.intake import IntakeService
from found_core.services.investigations import InvestigationService
from found_core.services.map import MapService
from found_core.services.notify import NotifyService
from found_core.services.people import PeopleService
from found_core.services.realtime import ConnectionService, PushService
from found_core.services.reports import ReportService
from found_core.services.resolve import ResolveService
from found_core.services.review import ReviewService
from found_core.services.runner import InvestigationRunner
from found_core.services.subscriptions import SubscriptionService
from found_core.services.watch import WatchService
from found_core.tools.service import AgentToolService

if TYPE_CHECKING:
    from found_core.adapters.apigw_connections import ApiGatewayConnections
    from found_core.adapters.dynamodb import DynamoBudgetLedger
    from found_core.adapters.local_agent import LocalAgentInvoker


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
def notify_service() -> NotifyService:
    """Email needs a sender (EMAIL_FROM); SMS stays off unless SMS_ENABLED is true."""
    import boto3

    from found_core.adapters.ses_email import SesEmail
    from found_core.adapters.sns_sms import SnsSms
    from found_core.ports.channels import Channel, DisabledChannel

    sender = os.environ.get("EMAIL_FROM", "").strip()
    email: Channel = SesEmail(boto3.client("ses"), sender) if sender else DisabledChannel("email")
    sms: Channel = (
        SnsSms(boto3.client("sns"))
        if os.environ.get("SMS_ENABLED", "").lower() == "true"
        else DisabledChannel("sms")
    )
    return NotifyService(repository(), email, sms)


@cache
def resolve_service() -> ResolveService:
    return ResolveService(repository())


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


@cache
def climate_service() -> ClimateService:
    return ClimateService(repository())


@cache
def map_service() -> MapService:
    return MapService(repository())


@cache
def investigation_config() -> InvestigationConfig:
    defaults = InvestigationConfig(model_id="")
    env = os.environ
    return InvestigationConfig(
        model_id=env["MODEL_ID"],
        prompt_version=env.get("PROMPT_VERSION", defaults.prompt_version),
        agent_version=env.get("AGENT_VERSION", defaults.agent_version),
        max_tool_calls=int(env.get("MAX_TOOL_CALLS", defaults.max_tool_calls)),
        run_cap=int(env.get("RUN_CAP", defaults.run_cap)),
        model_call_cap=int(env.get("MODEL_CALL_CAP", defaults.model_call_cap)),
    )


@cache
def agent_tool_service() -> AgentToolService:
    return AgentToolService(repository(), investigation_config())


def _table():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


@cache
def budget_ledger() -> "DynamoBudgetLedger":
    from found_core.adapters.dynamodb import DynamoBudgetLedger

    return DynamoBudgetLedger(_table())


@cache
def investigation_service() -> InvestigationService:
    import boto3

    from found_core.adapters.sqs_queue import SqsInvestigationQueue

    queue = SqsInvestigationQueue(boto3.client("sqs"), os.environ["RUN_QUEUE_URL"])
    return InvestigationService(repository(), budget_ledger(), queue, investigation_config())


@cache
def investigation_runner() -> InvestigationRunner:
    import boto3
    from botocore.config import Config

    from found_core.adapters.agentcore import AgentCoreInvoker

    config = investigation_config()
    if os.environ.get("AGENT_HOST") == "lambda":
        return InvestigationRunner(
            repository(), budget_ledger(), local_agent_invoker(config), config
        )
    client = boto3.client(
        "bedrock-agentcore",
        config=Config(
            # A quiet stream longer than the wall clock means the run is lost.
            read_timeout=config.wall_clock_seconds + 10,
            # A model-driven run is never retried automatically (cost).
            retries={"max_attempts": 1, "mode": "standard"},
        ),
    )
    invoker = AgentCoreInvoker(client, os.environ["RUNTIME_ARN"])
    return InvestigationRunner(repository(), budget_ledger(), invoker, config)


@cache
def review_service() -> ReviewService:
    return ReviewService(repository(), cursor_codec())


@cache
def demo_service() -> DemoService:
    import boto3

    from found_core.adapters.fixtures import LambdaResetTrigger, S3Fixtures

    repo = repository()
    fixtures = S3Fixtures(
        boto3.client("s3"), os.environ["FIXTURES_BUCKET"], os.environ["FIXTURES_PREFIX"]
    )
    worker = os.environ.get("RESET_FUNCTION_NAME")
    trigger = LambdaResetTrigger(boto3.client("lambda"), worker) if worker else None
    return DemoService(repo, IngestService(repo), fixtures, trigger)


def _bedrock_api_key() -> str | None:
    """The stored Bedrock API key, if this env reaches the model through bedrock-mantle."""
    import boto3

    arn = os.environ.get("BEDROCK_API_KEY_SECRET_ARN")
    if not arn:
        return None
    secret = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
    return secret["SecretString"].strip().strip("<>").strip() or None


@cache
def intake_service() -> IntakeService:
    """Uploads, the workflow steps and candidate decisions. The model is the agent's."""
    import boto3

    from found_core.adapters.extractors import ConverseExtractor, MantleExtractor, mantle_url
    from found_core.adapters.s3_store import S3ObjectStore
    from found_core.adapters.textract_reader import TextractReader

    repo = repository()
    bucket = os.environ["DATA_BUCKET"]
    model_id = os.environ.get("MODEL_ID", "")
    extractor = None
    if model_id:
        key = _bedrock_api_key()
        region = os.environ.get("AWS_REGION", "ap-south-1")
        extractor = (
            MantleExtractor(mantle_url(region), key, model_id)
            if key
            else ConverseExtractor(boto3.client("bedrock-runtime"), model_id)
        )
    return IntakeService(
        repo,
        IngestService(repo),
        S3ObjectStore(boto3.client("s3"), bucket),
        TextractReader(boto3.client("textract"), bucket),
        extractor,
    )


def local_agent_invoker(config: InvestigationConfig) -> "LocalAgentInvoker":
    """The agent in this process, reaching the model with the stored Bedrock API key."""
    from found_agent.config import AgentConfig
    from found_agent.models import build_model

    from found_core.adapters.local_agent import LocalAgentInvoker

    agent_config = AgentConfig(
        model_id=config.model_id,
        gateway_url="",
        region=os.environ.get("AWS_REGION", "ap-south-1"),
        api_key=_bedrock_api_key(),
    )
    return LocalAgentInvoker(
        agent_tool_service(),
        lambda: build_model(agent_config, config.max_output_tokens),
        model_id=config.model_id,
        read_timeout=config.wall_clock_seconds + 10,
    )
