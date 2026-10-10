"""Which Bedrock model client the agent uses.

With a Bedrock API key the agent calls models through the `bedrock-mantle` endpoint,
Bedrock's OpenAI-compatible API, using Strands' OpenAI provider. Without one it uses the
regular Bedrock provider and the role's AWS credentials. Either way the model only labels
and chooses tools; code validates every write.
"""

import os
from pathlib import Path
from typing import Any

from strands.models import BedrockModel
from strands.models.model import Model

from found_agent.config import AgentConfig

API_KEY_ENV = "BEDROCK_API_KEY"
DEFAULT_KEY_FILE = Path.home() / ".aws" / "bedrock-api-key"
MANTLE_URL = "https://bedrock-mantle.{region}.api.aws{path}"
# Mantle serves these model lines from /openai/v1 and every other one from /v1.
_OPENAI_PATH_PREFIXES = ("openai.gpt-5.", "openai.gpt-6-", "openai.gpt-6.", "xai.grok-4.",
                         "google.gemma-4-")  # fmt: skip


def mantle_base_url(region: str, model_id: str) -> str:
    path = "/openai/v1" if model_id.startswith(_OPENAI_PATH_PREFIXES) else "/v1"
    return MANTLE_URL.format(region=region, path=path)


def read_api_key(path: Path | None = None) -> str | None:
    """The key from the environment, else from a file outside the repo. Never logged."""
    key = os.environ.get(API_KEY_ENV)
    if not key:
        file = path or DEFAULT_KEY_FILE
        key = file.read_text(encoding="utf-8") if file.is_file() else None
    # A key pasted with the placeholder's angle brackets still works.
    key = (key or "").strip().strip("<>").strip()
    return key or None


def bedrock_model(config: AgentConfig, max_tokens: int) -> BedrockModel:
    settings: dict[str, Any] = {
        "model_id": config.model_id,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if config.guardrail_id and config.guardrail_version:
        # Prompt-attack filter over the untrusted report text.
        settings["guardrail_id"] = config.guardrail_id
        settings["guardrail_version"] = config.guardrail_version
    return BedrockModel(region_name=config.region, **settings)


def mantle_model(config: AgentConfig, max_tokens: int) -> Model:
    from strands.models.openai import OpenAIModel

    return OpenAIModel(
        client_args={
            "api_key": config.api_key,
            "base_url": mantle_base_url(config.region, config.model_id),
        },
        model_id=config.model_id,
        params={"max_tokens": max_tokens, "temperature": 0.0},
    )


def build_model(config: AgentConfig, max_tokens: int) -> Model:
    return mantle_model(config, max_tokens) if config.api_key else bedrock_model(config, max_tokens)
