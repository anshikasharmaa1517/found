"""Intake: S3 object created, then the `IntakeWorkflow` state machine (design 5.3, 6.8).

An object under `intake/` in the data bucket starts one Standard execution: validate the
object, read its text and ask the model for candidates, store them for review. Any
failure ends in the `fail` step, which records the reason on the job. One Lambda runs
every step; the state machine passes the step's name.

The text is read inside the Lambda rather than by a direct Textract task, because a
dense page's Textract response can exceed the state payload limit.
"""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from config import EnvConfig
from stacks.lambda_code import backend_code

INTAKE_PREFIX = "intake/"
STEP_TIMEOUT = cdk.Duration.seconds(90)
WORKFLOW_TIMEOUT = cdk.Duration.minutes(10)
# Transient failures worth another try: Textract throttling surfaces as ClientError.
RETRYABLE = ["ClientError", "Lambda.TooManyRequestsException", "Lambda.ServiceException"]


class IntakeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        table: ddb.ITableV2,
        bucket: s3.IBucket,
        model_id: str,
        api_key_secret: secretsmanager.ISecret | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        name = f"found-{cfg.name}"

        environment = {
            "TABLE_NAME": table.table_name,
            "DATA_BUCKET": bucket.bucket_name,
            "MODEL_ID": model_id,
            "POWERTOOLS_SERVICE_NAME": "intake",
            "LOG_LEVEL": "INFO",
        }
        if api_key_secret is not None:
            environment["BEDROCK_API_KEY_SECRET_ARN"] = api_key_secret.secret_arn

        self.function = lambda_.Function(
            self,
            "IntakeFunction",
            function_name=f"{name}-intake",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.intake.handler",
            code=backend_code(),
            memory_size=512,
            timeout=STEP_TIMEOUT,
            tracing=lambda_.Tracing.ACTIVE,
            environment=environment,
            log_group=logs.LogGroup(
                self,
                "IntakeLogs",
                retention=cfg.retention,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
        )
        table.grant_read_write_data(self.function)
        bucket.grant_read(self.function, f"{INTAKE_PREFIX}*")
        # Textract reads the object with the caller's permissions and has no resource ARN.
        self.function.add_to_role_policy(
            iam.PolicyStatement(actions=["textract:DetectDocumentText"], resources=["*"])
        )
        if api_key_secret is not None:
            api_key_secret.grant_read(self.function)
        else:
            self.function.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"],
                    resources=[
                        f"arn:{self.partition}:bedrock:{self.region}::foundation-model/{model_id}",
                        f"arn:{self.partition}:bedrock:{self.region}:{self.account}"
                        f":inference-profile/{model_id}",
                    ],
                )
            )

        def step(step_id: str, payload: dict, result_path: str | None) -> tasks.LambdaInvoke:
            return tasks.LambdaInvoke(
                self,
                step_id,
                lambda_function=self.function,
                payload=sfn.TaskInput.from_object(payload),
                payload_response_only=True,
                result_path=result_path,
            )

        key = sfn.JsonPath.string_at("$.detail.object.key")
        mark_failed = step(
            "MarkFailed",
            {"step": "fail", "key": key, "error": sfn.JsonPath.object_at("$.error")},
            sfn.JsonPath.DISCARD,
        ).next(sfn.Fail(self, "IntakeFailed", cause="See failure_reason on the intake job."))

        validate = step("ValidateObject", {"step": "validate", "key": key}, "$.validated")
        extract = step(
            "ExtractCandidates",
            {"step": "extract", "job_id": sfn.JsonPath.string_at("$.validated.job_id")},
            "$.extracted",
        )
        extract.add_retry(
            errors=RETRYABLE,
            interval=cdk.Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2,
        )
        store = step(
            "StoreCandidates",
            {
                "step": "store",
                "job_id": sfn.JsonPath.string_at("$.validated.job_id"),
                "candidates": sfn.JsonPath.list_at("$.extracted.candidates"),
            },
            "$.stored",
        )
        for task in (validate, extract, store):
            task.add_catch(mark_failed, errors=["States.ALL"], result_path="$.error")

        duplicate = sfn.Succeed(self, "AlreadyStarted")
        definition = validate.next(
            sfn.Choice(self, "IsNewJob")
            .when(sfn.Condition.string_equals("$.validated.kind", "duplicate"), duplicate)
            .otherwise(extract.next(store))
        )
        self.workflow = sfn.StateMachine(
            self,
            "IntakeWorkflow",
            state_machine_name=f"{name}-intake",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=WORKFLOW_TIMEOUT,
            tracing_enabled=True,
        )

        # The data bucket sends its object events to the default bus (Data stack).
        events.Rule(
            self,
            "IntakeObjectCreated",
            rule_name=f"{name}-intake-object-created",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created"],
                detail={
                    "bucket": {"name": [bucket.bucket_name]},
                    "object": {"key": [{"prefix": INTAKE_PREFIX}]},
                },
            ),
            targets=[targets.SfnStateMachine(self.workflow)],
        )

        cdk.CfnOutput(self, "IntakeWorkflowArn", value=self.workflow.state_machine_arn)
