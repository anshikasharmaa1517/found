"""AgentCore Runtime entrypoint. The runner invokes it with the investigation as session."""

from collections.abc import AsyncIterator
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError
from strands.models import BedrockModel

from found_agent.config import AgentConfig
from found_agent.gateway import gateway_client
from found_agent.run import RunRequest, run_investigation

app = BedrockAgentCoreApp()


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


@app.entrypoint
async def investigate(payload: dict[str, Any], context: Any) -> AsyncIterator[dict[str, Any]]:
    try:
        request = RunRequest.model_validate(payload)
    except ValidationError:
        yield {
            "type": "done",
            "finding_recorded": False,
            "stop_reason": "ERROR",
            "error_code": "BAD_REQUEST",
        }
        return
    config = AgentConfig.from_env()
    model = bedrock_model(config, request.limits.max_output_tokens)
    tools = gateway_client(config.gateway_url, config.region)
    async for event in run_investigation(
        request, model, [tools], model_id=config.model_id, agent_version=config.agent_version
    ):
        yield event


if __name__ == "__main__":
    app.run()
