"""Per-environment settings, read from the `envs` block in cdk.json."""

from dataclasses import dataclass
from typing import Any

REGION = "ap-south-1"


@dataclass(frozen=True)
class EnvConfig:
    name: str
    deletion_protection: bool
    web_origins: tuple[str, ...]


def load(name: str, envs: dict[str, Any]) -> EnvConfig:
    if name not in envs:
        raise ValueError(f"unknown env {name!r}, expected one of {sorted(envs)}")
    raw = envs[name]
    return EnvConfig(
        name=name,
        deletion_protection=bool(raw["deletion_protection"]),
        web_origins=tuple(raw["web_origins"]),
    )
