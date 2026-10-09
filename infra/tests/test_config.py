import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_logs as logs
from aws_cdk.assertions import Template

from config import load
from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack

ENVS = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]["envs"]
ENV = cdk.Environment(account="111111111111", region="ap-south-1")


def test_dev_is_cheap_and_demo_uses_the_design_caps():
    dev, demo = load("dev", ENVS), load("demo", ENVS)
    assert dev.retention == logs.RetentionDays.ONE_WEEK
    assert (dev.run_cap, dev.model_call_cap) == (30, 200)
    assert demo.retention == logs.RetentionDays.ONE_MONTH
    assert (demo.run_cap, demo.model_call_cap) == (50, 300)


def test_missing_cost_settings_fall_back_to_safe_defaults():
    cfg = load("x", {"x": {"deletion_protection": False, "web_origins": []}})
    assert cfg.retention == logs.RetentionDays.ONE_MONTH
    assert cfg.cap_environment() == {"RUN_CAP": "200", "MODEL_CALL_CAP": "1200"}


def test_dev_settings_reach_the_templates():
    app = cdk.App(context={"aws:cdk:bundling-stacks": []})
    cfg = load("dev", ENVS)
    data = DataStack(app, "Data", cfg=cfg, env=ENV)
    auth = AuthStack(app, "Auth", cfg=cfg, env=ENV)
    agent = AgentStack(app, "Agent", cfg=cfg, table=data.table, env=ENV)
    api = ApiStack(
        app,
        "Api",
        cfg=cfg,
        table=data.table,
        run_queue=agent.run_queue,
        model_id=agent.model_id,
        user_pool=auth.user_pool,
        web_client=auth.web_client,
        env=ENV,
    )
    for stack in (api, agent):
        t = Template.from_stack(stack)
        days = {
            g["Properties"]["RetentionInDays"]
            for g in t.find_resources("AWS::Logs::LogGroup").values()
        }
        assert days == {7}
    functions = {
        f["Properties"].get("FunctionName"): f["Properties"]
        for stack in (api, agent)
        for f in Template.from_stack(stack).find_resources("AWS::Lambda::Function").values()
    }
    for name in ("found-dev-api", "found-dev-investigation-runner"):
        env = functions[name]["Environment"]["Variables"]
        assert (env["RUN_CAP"], env["MODEL_CALL_CAP"]) == ("30", "200")
