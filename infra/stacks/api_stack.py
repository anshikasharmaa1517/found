"""HTTP API with a Cognito JWT authorizer and the `api` Lambda (design Sections 4.3, 7.1, 7.2)."""

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from config import EnvConfig
from stacks.lambda_code import ROOT, backend_code

FIXTURES = ROOT / "data" / "fixtures"
FIXTURES_PREFIX = "fixtures"
DEMO_VERSION = "demo-v1"

REPORTS_ROUTE = "POST /v1/incidents/{incident_id}/reports"
INVESTIGATE_ROUTE = "POST /v1/claims/{claim_id}/investigations"
# Every route below needs a signed-in user; the service checks the role.
SIGNED_IN_ROUTES = (
    ("GET", "/v1/incidents/{incident_id}/people"),
    ("GET", "/v1/people/{person_id}"),
    ("GET", "/v1/people/{person_id}/timeline"),
    ("GET", "/v1/incidents/{incident_id}/map"),
    ("POST", "/v1/people/{person_id}/subscriptions"),
    ("DELETE", "/v1/subscriptions/{subscription_id}"),
    ("GET", "/v1/me/subscriptions"),
    ("GET", "/v1/me/alerts"),
    ("POST", "/v1/claims/{claim_id}/investigations"),
    ("GET", "/v1/investigations/{investigation_id}"),
    ("POST", "/v1/investigations/{investigation_id}/review"),
    ("GET", "/v1/incidents/{incident_id}/review-queue"),
    ("POST", "/v1/incidents/{incident_id}/review-items/{review_id}/resolve"),
    ("GET", "/v1/incidents/{incident_id}/activity"),
    ("POST", "/v1/admin/incidents/{incident_id}/reset"),
    ("GET", "/v1/admin/investigations/{investigation_id}/recording"),
)
DEFAULT_THROTTLE = {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40}
ROUTE_THROTTLES = {
    REPORTS_ROUTE: {"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20},
    INVESTIGATE_ROUTE: {"ThrottlingRateLimit": 2, "ThrottlingBurstLimit": 5},
}


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
        run_queue: sqs.IQueue,
        model_id: str,
        user_pool: cognito.IUserPool,
        web_client: cognito.IUserPoolClient,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # HMAC key for pagination cursors, so clients cannot forge positions.
        self.cursor_secret = secretsmanager.Secret(
            self,
            "CursorSecret",
            description="Signs pagination cursors of the HTTP API.",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64, exclude_punctuation=True
            ),
        )

        # Demo fixtures, copied from data/fixtures on every deploy (design Section 5.5).
        self.fixtures_bucket = s3.Bucket(
            self,
            "FixturesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN
            if cfg.deletion_protection
            else cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=not cfg.deletion_protection,
        )
        s3deploy.BucketDeployment(
            self,
            "FixturesDeployment",
            sources=[s3deploy.Source.asset(str(FIXTURES))],
            destination_bucket=self.fixtures_bucket,
            destination_key_prefix=FIXTURES_PREFIX,
        )
        fixtures_env = {
            "FIXTURES_BUCKET": self.fixtures_bucket.bucket_name,
            "FIXTURES_PREFIX": f"{FIXTURES_PREFIX}/{DEMO_VERSION}",
        }

        # Reset worker: a full reload outlasts the API timeout, so it runs on its own.
        self.reset_function = lambda_.Function(
            self,
            "DemoResetFunction",
            function_name=f"found-{cfg.name}-demo-reset",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.demo_reset.handler",
            code=backend_code(),
            memory_size=512,
            timeout=cdk.Duration.minutes(5),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                **fixtures_env,
                "POWERTOOLS_SERVICE_NAME": "demo_reset",
                "LOG_LEVEL": "INFO",
            },
            log_group=logs.LogGroup(
                self,
                "DemoResetLogs",
                retention=cfg.retention,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.reset_function)
        self.fixtures_bucket.grant_read(self.reset_function)

        self.function = lambda_.Function(
            self,
            "ApiFunction",
            function_name=f"found-{cfg.name}-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.api.handler",
            code=backend_code(),
            memory_size=512,
            timeout=cdk.Duration.seconds(10),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                "RUN_QUEUE_URL": run_queue.queue_url,
                # Part of every evidence fingerprint; must be the model the agent runs.
                "MODEL_ID": model_id,
                "CURSOR_SECRET_ARN": self.cursor_secret.secret_arn,
                **fixtures_env,
                **cfg.cap_environment(),
                "RESET_FUNCTION_NAME": self.reset_function.function_name,
                "POWERTOOLS_SERVICE_NAME": "api",
                "LOG_LEVEL": "INFO",
            },
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=cfg.retention,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.function)
        self.cursor_secret.grant_read(self.function)
        run_queue.grant_send_messages(self.function)
        self.fixtures_bucket.grant_read(self.function)
        self.reset_function.grant_invoke(self.function)

        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"found-{cfg.name}-http",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=list(cfg.web_origins),
                allow_headers=["authorization", "content-type"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.DELETE,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                expose_headers=["x-request-id"],
                max_age=cdk.Duration.hours(1),
            ),
        )

        # The ID token carries `cognito:groups` and `custom:org_id`; its audience is the client.
        issuer = f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}"
        jwt = authorizers.HttpJwtAuthorizer(
            "Cognito", jwt_issuer=issuer, jwt_audience=[web_client.user_pool_client_id]
        )
        integration = integrations.HttpLambdaIntegration("Api", self.function)

        routes = self.http_api.add_routes(
            path="/v1/health", methods=[apigw.HttpMethod.GET], integration=integration
        )
        routes += self.http_api.add_routes(
            path="/v1/incidents/{incident_id}/reports",
            methods=[apigw.HttpMethod.POST],
            integration=integration,
            authorizer=jwt,
        )
        for method, path in SIGNED_IN_ROUTES:
            routes += self.http_api.add_routes(
                path=path,
                methods=[apigw.HttpMethod(method)],
                integration=integration,
                authorizer=jwt,
            )

        stage = self.http_api.default_stage.node.default_child
        stage.add_property_override("DefaultRouteSettings", DEFAULT_THROTTLE)
        stage.add_property_override("RouteSettings", ROUTE_THROTTLES)
        # Route settings name routes by key, so every route must exist before the stage.
        for route in routes:
            stage.node.add_dependency(route)

        cdk.CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
