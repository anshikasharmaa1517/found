"""WebSocket API with token check on connect, and live push from the bus.

Design Sections 5.4, 6.5 and 7.5. Lambdas: `ws_authorizer` checks the Cognito ID token,
`ws` manages connections and subscriptions, `ws_push` fans events out to connections.
"""

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from config import EnvConfig
from stacks.consumer import event_consumer, inserted, modified
from stacks.lambda_code import backend_code

STAGE = "prod"
TOKEN_SOURCE = "route.request.querystring.token"


class RealtimeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
        bus: events.IEventBus,
        user_pool: cognito.IUserPool,
        web_client: cognito.IUserPoolClient,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self._cfg = cfg

        self.api = apigw.WebSocketApi(self, "WebSocketApi", api_name=f"found-{cfg.name}-ws")
        # Built from parts: referencing the stage from the functions would form a cycle.
        endpoint = f"https://{self.api.api_id}.execute-api.{self.region}.amazonaws.com/{STAGE}"
        manage = iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[
                f"arn:{self.partition}:execute-api:{self.region}:{self.account}:"
                f"{self.api.api_id}/{STAGE}/*/@connections/*"
            ],
        )

        authorizer_fn = self._function(
            "WsAuthorizer",
            "handlers.ws_authorizer.handler",
            {
                "USER_POOL_ID": user_pool.user_pool_id,
                "USER_POOL_CLIENT_ID": web_client.user_pool_client_id,
            },
        )
        self.ws_function = self._function(
            "Ws", "handlers.ws.handler", {"TABLE_NAME": table.table_name, "WS_ENDPOINT": endpoint}
        )
        table.grant_read_write_data(self.ws_function)
        self.ws_function.add_to_role_policy(manage)

        integration = integrations.WebSocketLambdaIntegration("Ws", self.ws_function)
        self.api.add_route(
            "$connect",
            integration=integration,
            authorizer=authorizers.WebSocketLambdaAuthorizer(
                "Token", authorizer_fn, identity_source=[TOKEN_SOURCE]
            ),
        )
        self.api.add_route("$disconnect", integration=integration)
        self.api.add_route("subscribe", integration=integration, return_response=True)
        self.api.add_route("$default", integration=integration, return_response=True)

        self.stage = apigw.WebSocketStage(
            self, "Stage", web_socket_api=self.api, stage_name=STAGE, auto_deploy=True
        )

        self.push_function = event_consumer(
            self,
            "WsPush",
            env_name=cfg.name,
            handler="handlers.ws_push.handler",
            rules=[
                ("push-claim", inserted("CLAIM")),
                ("push-alert", inserted("ALERT")),
                ("push-review", inserted("REVIEW_ITEM")),
                ("push-investigation-step", inserted("INVESTIGATION_STEP")),
                ("investigation-changed", modified("INVESTIGATION")),
            ],
            bus=bus,
            table=table,
            environment={"WS_ENDPOINT": endpoint},
        )
        self.push_function.add_to_role_policy(manage)

        cdk.CfnOutput(self, "WebSocketUrl", value=self.stage.url)

    def _function(self, name: str, handler: str, environment: dict[str, str]) -> lambda_.Function:
        return lambda_.Function(
            self,
            f"{name}Function",
            function_name=f"found-{self._cfg.name}-{name.lower()}",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=backend_code(),
            memory_size=256,
            timeout=cdk.Duration.seconds(10),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "POWERTOOLS_SERVICE_NAME": name.lower(),
                "LOG_LEVEL": "INFO",
                **environment,
            },
            log_group=logs.LogGroup(
                self,
                f"{name}Logs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
