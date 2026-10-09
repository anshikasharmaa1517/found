"""Provenance agent: tools Lambda, Gateway, guardrail, Runtime and the run queue.

Design Sections 4.3, 5.2, 9.9 and 12.2. The agent reaches data only through the
Gateway, which signs nothing itself: the Runtime role signs each call (IAM inbound
auth), and the Gateway role invokes the tools Lambda. The run queue feeds the runner,
which invokes the Runtime. At most two runs proceed at once: the queue's event source
caps concurrency, and no Lambda concurrency is reserved (owner decision 3).

The Bedrock model is a deploy-time parameter (`ModelId`), so choosing one needs no
code change. It may be a foundation model ID or an inference profile ID.
"""

import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as sources
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from config import EnvConfig
from stacks.consumer import dead_letter_queue
from stacks.lambda_code import BACKEND, agent_code, backend_code

TOOL_SPECS = BACKEND / "found_core" / "tools" / "specs.json"
GATEWAY_TARGET = "found-tools"
MAX_TOOL_CALLS = 8
MAX_CONCURRENT_RUNS = 2
# Wall clock 120 s plus room to store the last steps and the outcome.
RUNNER_TIMEOUT = cdk.Duration.seconds(180)

# SQS to runner: two receives, then the dead-letter queue (design Section 10.4).
RUN_VISIBILITY = cdk.Duration.seconds(300)
RUN_MAX_RECEIVES = 2

AGENTCORE = "bedrock-agentcore.amazonaws.com"


def load_tool_specs(path: Path = TOOL_SPECS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(node: dict) -> agentcore.CfnGatewayTarget.SchemaDefinitionProperty:
    return agentcore.CfnGatewayTarget.SchemaDefinitionProperty(
        type=node["type"],
        description=node.get("description"),
        properties={k: _schema(v) for k, v in node["properties"].items()}
        if "properties" in node
        else None,
        required=node.get("required"),
        items=_schema(node["items"]) if "items" in node else None,
    )


class AgentStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = f"found-{cfg.name}"

        self.model_id = cdk.CfnParameter(
            self,
            "ModelId",
            type="String",
            min_length=1,
            description="Bedrock model ID or inference profile ID used by the agent.",
        ).value_as_string

        # Run queue, consumed by the runner below.
        self.run_dlq = dead_letter_queue(self, "RunDlq", f"{name}-investigation-dlq")
        self.run_queue = sqs.Queue(
            self,
            "RunQueue",
            queue_name=f"{name}-investigation-queue",
            visibility_timeout=RUN_VISIBILITY,
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(
                queue=self.run_dlq, max_receive_count=RUN_MAX_RECEIVES
            ),
        )

        self.tools_function = lambda_.Function(
            self,
            "ToolsFunction",
            function_name=f"{name}-agent-tools",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.agent_tools.handler",
            code=backend_code(),
            memory_size=256,
            timeout=cdk.Duration.seconds(15),
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                "MODEL_ID": self.model_id,
                "MAX_TOOL_CALLS": str(MAX_TOOL_CALLS),
                "POWERTOOLS_SERVICE_NAME": "agent_tools",
                "LOG_LEVEL": "INFO",
            },
            log_group=logs.LogGroup(
                self,
                "ToolsLogs",
                retention=cfg.retention,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.tools_function)

        gateway_role = iam.Role(
            self,
            "GatewayRole",
            assumed_by=iam.ServicePrincipal(
                AGENTCORE, conditions={"StringEquals": {"aws:SourceAccount": self.account}}
            ),
        )
        self.tools_function.grant_invoke(gateway_role)

        self.gateway = agentcore.CfnGateway(
            self,
            "Gateway",
            name=f"{name}-tools",
            description="Tools of the provenance agent. The only path from the agent to data.",
            authorizer_type="AWS_IAM",
            protocol_type="MCP",
            role_arn=gateway_role.role_arn,
            exception_level="DEBUG" if cfg.name == "dev" else None,
        )
        self.gateway_target = agentcore.CfnGatewayTarget(
            self,
            "GatewayTarget",
            name=GATEWAY_TARGET,
            gateway_identifier=self.gateway.attr_gateway_identifier,
            credential_provider_configurations=[
                agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="GATEWAY_IAM_ROLE"
                )
            ],
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    lambda_=agentcore.CfnGatewayTarget.McpLambdaTargetConfigurationProperty(
                        lambda_arn=self.tools_function.function_arn,
                        tool_schema=agentcore.CfnGatewayTarget.ToolSchemaProperty(
                            inline_payload=[
                                agentcore.CfnGatewayTarget.ToolDefinitionProperty(
                                    name=spec["name"],
                                    description=spec["description"],
                                    input_schema=_schema(spec["inputSchema"]),
                                )
                                for spec in load_tool_specs()
                            ]
                        ),
                    )
                )
            ),
        )
        # Gateway checks it can invoke the target when the target is created.
        self.gateway_target.node.add_dependency(gateway_role)

        # Prompt-attack filter on input: report text is untrusted.
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name=f"{name}-agent",
            description="Blocks prompt attacks carried in report text.",
            blocked_input_messaging="This input was blocked.",
            blocked_outputs_messaging="This output was blocked.",
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="PROMPT_ATTACK", input_strength="HIGH", output_strength="NONE"
                    )
                ]
            ),
        )
        self.guardrail_version = bedrock.CfnGuardrailVersion(
            self, "GuardrailVersion", guardrail_identifier=self.guardrail.attr_guardrail_id
        )

        code = agent_code(self, "AgentCode")
        runtime_role = iam.Role(
            self,
            "RuntimeRole",
            assumed_by=iam.ServicePrincipal(
                AGENTCORE, conditions={"StringEquals": {"aws:SourceAccount": self.account}}
            ),
        )
        code.grant_read(runtime_role)
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    # Inference profiles route to foundation models in other regions.
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{self.model_id}",
                ],
            )
        )
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[self.guardrail.attr_guardrail_arn]
            )
        )
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeGateway"],
                resources=[self.gateway.attr_gateway_arn],
            )
        )
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/*"
                ],
            )
        )
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"], resources=["*"]
            )
        )

        self.runtime = agentcore.CfnRuntime(
            self,
            "Runtime",
            agent_runtime_name=f"found_{cfg.name}_agent",
            description="Provenance agent. Payload holds IDs and limits only.",
            role_arn=runtime_role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                    code=agentcore.CfnRuntime.CodeProperty(
                        s3=agentcore.CfnRuntime.S3LocationProperty(
                            bucket=code.s3_bucket_name, prefix=code.s3_object_key
                        )
                    ),
                    entry_point=["main.py"],
                    runtime="PYTHON_3_12",
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            lifecycle_configuration=agentcore.CfnRuntime.LifecycleConfigurationProperty(
                idle_runtime_session_timeout=300, max_lifetime=900
            ),
            environment_variables={
                "MODEL_ID": self.model_id,
                "GATEWAY_URL": self.gateway.attr_gateway_url,
                "GUARDRAIL_ID": self.guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": self.guardrail_version.attr_version,
            },
        )
        # The Runtime validates its role on create, so the policy must exist first.
        self.runtime.node.add_dependency(runtime_role)

        self.runner = lambda_.Function(
            self,
            "RunnerFunction",
            function_name=f"{name}-investigation-runner",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.investigation_runner.handler",
            code=backend_code(),
            memory_size=256,
            timeout=RUNNER_TIMEOUT,
            tracing=lambda_.Tracing.ACTIVE,
            environment={
                "TABLE_NAME": table.table_name,
                "MODEL_ID": self.model_id,
                "RUNTIME_ARN": self.runtime.attr_agent_runtime_arn,
                **cfg.cap_environment(),
                "POWERTOOLS_SERVICE_NAME": "investigation_runner",
                "LOG_LEVEL": "INFO",
            },
            log_group=logs.LogGroup(
                self,
                "RunnerLogs",
                retention=cfg.retention,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.runner)
        self.runner.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    self.runtime.attr_agent_runtime_arn,
                    f"{self.runtime.attr_agent_runtime_arn}/*",
                ],
            )
        )
        self.runner.add_event_source(
            sources.SqsEventSource(
                self.run_queue,
                batch_size=1,
                max_concurrency=MAX_CONCURRENT_RUNS,
                report_batch_item_failures=True,
            )
        )

        cdk.CfnOutput(self, "RuntimeArn", value=self.runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "GatewayUrl", value=self.gateway.attr_gateway_url)
        cdk.CfnOutput(self, "RunQueueUrl", value=self.run_queue.queue_url)
        cdk.CfnOutput(self, "RunDlqUrl", value=self.run_dlq.queue_url)
