import json
from pathlib import Path

import aws_cdk as cdk
import pytest

from app import build

CDK_JSON = Path(__file__).resolve().parents[1] / "cdk.json"


def synth(tmp_path, **context):
    """Build the app with the context from cdk.json, as the CDK CLI would."""
    base = json.loads(CDK_JSON.read_text())["context"]
    # Skip bundling so tests do not install packages.
    app = cdk.App(
        context={**base, "aws:cdk:bundling-stacks": [], **context}, outdir=str(tmp_path)
    )
    build(app)
    app.synth()
    return {p.name for p in tmp_path.glob("*.template.json")}


@pytest.mark.parametrize("env_name", ["dev", "demo"])
def test_app_synthesizes_each_environment(tmp_path, env_name):
    assert synth(tmp_path, env=env_name) == {
        f"Found-{env_name}-Data.template.json",
        f"Found-{env_name}-Events.template.json",
        f"Found-{env_name}-Auth.template.json",
        f"Found-{env_name}-Api.template.json",
        f"Found-{env_name}-Realtime.template.json",
    }


def test_app_rejects_unknown_environment(tmp_path):
    with pytest.raises(ValueError):
        synth(tmp_path, env="prod")
