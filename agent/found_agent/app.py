"""AgentCore Runtime entrypoint. The runner invokes it with the investigation as session."""

from collections.abc import AsyncIterator
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError

from found_agent.config import AgentConfig
from found_agent.gateway import gateway_client
from found_agent.models import bedrock_model, build_model
from found_agent.run import RunRequest, run_investigation

app = BedrockAgentCoreApp()


__all__ = ["app", "bedrock_model", "build_model", "investigate"]


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
    model = build_model(config, request.limits.max_output_tokens)
    tools = gateway_client(config.gateway_url, config.region)
    async for event in run_investigation(
        request, model, [tools], model_id=config.model_id, agent_version=config.agent_version
    ):
        yield event


if __name__ == "__main__":
    app.run()
