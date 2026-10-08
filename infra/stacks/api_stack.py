"""HTTP API with a Cognito JWT authorizer and the `api` Lambda (design Sections 4.3, 7.1, 7.2)."""

import shutil
import subprocess
import sys
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from config import EnvConfig

BACKEND = Path(__file__).resolve().parents[2] / "backend"
PACKAGES = ("found_core", "handlers")
ASSET_EXCLUDE = ["tests", "build", "*.egg-info", "**/__pycache__", ".pytest_cache", ".ruff_cache"]


@jsii.implements(cdk.ILocalBundling)
class _LocalBundling:
    """Installs Linux arm64 wheels with the local pip, so Docker is only a fallback."""

    def try_bundle(self, output_dir: str, _options: object = None) -> bool:
        cmd = [
            sys.executable, "-m", "pip", "install", "--quiet",
            "-r", str(BACKEND / "requirements-lambda.txt"),
            "--target", output_dir,
            "--platform", "manylinux2014_aarch64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
        ]  # fmt: skip
        if subprocess.run(cmd, check=False).returncode != 0:
            return False
        for package in PACKAGES:
            shutil.copytree(
                BACKEND / package,
                Path(output_dir) / package,
                ignore=shutil.ignore_patterns("__pycache__"),
                dirs_exist_ok=True,
            )
        return True


def backend_code() -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(BACKEND),
        exclude=ASSET_EXCLUDE,
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            platform="linux/arm64",
            local=_LocalBundling(),
            command=[
                "bash",
                "-c",
                "pip install -r requirements-lambda.txt -t /asset-output"
                " && cp -r found_core handlers /asset-output",
            ],
        ),
    )


REPORTS_ROUTE = "POST /v1/incidents/{incident_id}/reports"
# Every route below needs a signed-in user; the service checks the role.
SIGNED_IN_ROUTES = (
    ("GET", "/v1/incidents/{incident_id}/people"),
    ("GET", "/v1/people/{person_id}"),
    ("GET", "/v1/people/{person_id}/timeline"),
)
DEFAULT_THROTTLE = {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40}
ROUTE_THROTTLES = {REPORTS_ROUTE: {"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20}}


class ApiStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
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
                "CURSOR_SECRET_ARN": self.cursor_secret.secret_arn,
                "POWERTOOLS_SERVICE_NAME": "api",
                "LOG_LEVEL": "INFO",
            },
            log_group=logs.LogGroup(
                self,
                "ApiLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.function)
        self.cursor_secret.grant_read(self.function)

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

        self.http_api.add_routes(
            path="/v1/health", methods=[apigw.HttpMethod.GET], integration=integration
        )
        self.http_api.add_routes(
            path="/v1/incidents/{incident_id}/reports",
            methods=[apigw.HttpMethod.POST],
            integration=integration,
            authorizer=jwt,
        )
        for method, path in SIGNED_IN_ROUTES:
            self.http_api.add_routes(
                path=path,
                methods=[apigw.HttpMethod(method)],
                integration=integration,
                authorizer=jwt,
            )

        stage = self.http_api.default_stage.node.default_child
        stage.add_property_override("DefaultRouteSettings", DEFAULT_THROTTLE)
        stage.add_property_override("RouteSettings", ROUTE_THROTTLES)

        cdk.CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
