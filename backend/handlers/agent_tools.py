"""Gateway Lambda target for the agent tools (design Section 9.9).

Gateway passes the tool arguments as the event and names the tool in the client
context as `{target}___{tool}`. Tool errors go back to the agent as data, so it can
correct a call; only unexpected failures raise.
"""

from typing import Any

from aws_lambda_powertools import Logger

from found_core import container

logger = Logger(service="agent_tools")

TOOL_NAME_KEY = "bedrockAgentCoreToolName"
TARGET_DELIMITER = "___"


def tool_name(context: Any) -> str:
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None) or {}
    name = str(custom.get(TOOL_NAME_KEY, ""))
    return name.split(TARGET_DELIMITER, 1)[1] if TARGET_DELIMITER in name else name


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    tool = tool_name(context)
    arguments = event if isinstance(event, dict) else {}
    logger.append_keys(tool=tool, investigation_id=arguments.get("investigation_id"))
    result = container.agent_tool_service().call(tool, arguments)
    if result.get("ok"):
        logger.info("tool call", extra={"tool_calls_left": result.get("tool_calls_left")})
    else:
        logger.warning("tool call refused", extra={"error_code": result["error"]["code"]})
    return result
