"""CDK entry point. Select the environment with `-c env=dev` or `-c env=demo`."""

import os

import aws_cdk as cdk

from config import REGION, load
from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.events_stack import EventsStack
from stacks.intake_stack import IntakeStack
from stacks.maps_stack import MapsStack
from stacks.observability_stack import ObservabilityStack
from stacks.realtime_stack import RealtimeStack


def build(app: cdk.App) -> None:
    cfg = load(app.node.try_get_context("env") or "dev", app.node.try_get_context("envs") or {})
    env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)

    data = DataStack(app, f"Found-{cfg.name}-Data", cfg=cfg, env=env)
    events = EventsStack(app, f"Found-{cfg.name}-Events", cfg=cfg, table=data.table, env=env)
    auth = AuthStack(app, f"Found-{cfg.name}-Auth", cfg=cfg, env=env)
    agent = AgentStack(app, f"Found-{cfg.name}-Agent", cfg=cfg, table=data.table, env=env)
    ApiStack(
        app,
        f"Found-{cfg.name}-Api",
        cfg=cfg,
        table=data.table,
        bucket=data.bucket,
        run_queue=agent.run_queue,
        model_id=cfg.model_id,
        user_pool=auth.user_pool,
        web_client=auth.web_client,
        env=env,
    )

    RealtimeStack(
        app,
        f"Found-{cfg.name}-Realtime",
        cfg=cfg,
        table=data.table,
        bus=events.bus,
        user_pool=auth.user_pool,
        web_client=auth.web_client,
        env=env,
    )

    MapsStack(app, f"Found-{cfg.name}-Maps", cfg=cfg, env=env)

    IntakeStack(
        app,
        f"Found-{cfg.name}-Intake",
        cfg=cfg,
        table=data.table,
        bucket=data.bucket,
        model_id=cfg.model_id,
        api_key_secret=agent.api_key_secret,
        env=env,
    )

    ObservabilityStack(app, f"Found-{cfg.name}-Observability", cfg=cfg, env=env)

    cdk.Tags.of(app).add("project", "found")
    cdk.Tags.of(app).add("env", cfg.name)


if __name__ == "__main__":
    app = cdk.App()
    build(app)
    app.synth()
