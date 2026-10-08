"""CDK entry point. Select the environment with `-c env=dev` or `-c env=demo`."""

import os

import aws_cdk as cdk

from config import REGION, load
from stacks.data_stack import DataStack


def build(app: cdk.App) -> None:
    cfg = load(app.node.try_get_context("env") or "dev", app.node.try_get_context("envs") or {})
    env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)

    DataStack(app, f"Found-{cfg.name}-Data", cfg=cfg, env=env)

    cdk.Tags.of(app).add("project", "found")
    cdk.Tags.of(app).add("env", cfg.name)


if __name__ == "__main__":
    app = cdk.App()
    build(app)
    app.synth()
