"""Per-environment settings, read from the `envs` block in cdk.json."""

from dataclasses import dataclass
from typing import Any

from aws_cdk import aws_logs as logs

REGION = "ap-south-1"
AGENT_HOSTS = ("agentcore", "lambda")


@dataclass(frozen=True)
class EnvConfig:
    name: str
    deletion_protection: bool
    web_origins: tuple[str, ...]
    # Cost controls (free credit is limited): how long logs are kept, and the monthly
    # caps on investigation runs and model calls that the budget ledger enforces.
    log_retention: str = "ONE_MONTH"
    run_cap: int = 200
    model_call_cap: int = 1200
    # Where the agent runs: "agentcore" (the design) or "lambda" (inside the runner,
    # for accounts without AgentCore Runtime).
    agent_host: str = "agentcore"

    @property
    def retention(self) -> logs.RetentionDays:
        return logs.RetentionDays[self.log_retention]

    def cap_environment(self) -> dict[str, str]:
        return {"RUN_CAP": str(self.run_cap), "MODEL_CALL_CAP": str(self.model_call_cap)}


def load(name: str, envs: dict[str, Any]) -> EnvConfig:
    if name not in envs:
        raise ValueError(f"unknown env {name!r}, expected one of {sorted(envs)}")
    raw = envs[name]
    agent_host = str(raw.get("agent_host", "agentcore"))
    if agent_host not in AGENT_HOSTS:
        raise ValueError(f"agent_host must be one of {AGENT_HOSTS}, not {agent_host!r}")
    return EnvConfig(
        name=name,
        deletion_protection=bool(raw["deletion_protection"]),
        web_origins=tuple(raw["web_origins"]),
        log_retention=str(raw.get("log_retention", "ONE_MONTH")),
        run_cap=int(raw.get("run_cap", 200)),
        model_call_cap=int(raw.get("model_call_cap", 1200)),
        agent_host=agent_host,
    )
