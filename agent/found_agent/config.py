"""Runtime settings, read once from the environment of the AgentCore Runtime."""

import os
from dataclasses import dataclass, field

AGENT_VERSION = "0.1.0"


@dataclass(frozen=True)
class AgentConfig:
    model_id: str
    gateway_url: str
    region: str
    guardrail_id: str | None = None
    guardrail_version: str | None = None
    agent_version: str = AGENT_VERSION
    # A Bedrock API key routes model calls through the bedrock-mantle endpoint.
    api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        env = os.environ
        return cls(
            model_id=env["MODEL_ID"],
            gateway_url=env["GATEWAY_URL"],
            region=env.get("AWS_REGION", "ap-south-1"),
            guardrail_id=env.get("GUARDRAIL_ID") or None,
            guardrail_version=env.get("GUARDRAIL_VERSION") or None,
            api_key=env.get("BEDROCK_API_KEY") or None,
        )
