"""Runs the provenance agent inside this process instead of on AgentCore Runtime.

Used where AgentCore Runtime is not available. The agent is the same `found_agent`
loop, the model is reached through the configured client, and the tools are the
`AgentToolService` called directly, so every check the Gateway path makes still holds.
The runner sees the same event stream either way.

`found_agent` and its libraries come from the runner's Lambda layer; they are imported
only when a run starts, so the other Lambdas never need them.
"""

import asyncio
import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from found_core.ports.agent import AgentTimeout, AgentUnavailable
from found_core.tools.arguments import TOOL_ARGS, TOOL_DESCRIPTIONS, input_schema
from found_core.tools.service import AgentToolService

_DONE = object()


def local_tools(service: AgentToolService) -> list[Any]:
    """Each tool as a Strands tool that answers with the tools service's JSON body."""
    from strands.tools import PythonAgentTool

    def make(name: str) -> PythonAgentTool:
        def call(tool_use: dict[str, Any], **_: Any) -> dict[str, Any]:
            body = service.call(name, dict(tool_use.get("input") or {}))
            return {
                "toolUseId": tool_use["toolUseId"],
                "status": "success",
                "content": [{"text": json.dumps(body)}],
            }

        spec = {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "inputSchema": {"json": input_schema(TOOL_ARGS[name])},
        }
        return PythonAgentTool(name, spec, call)

    return [make(name) for name in TOOL_ARGS]


class LocalAgentInvoker:
    def __init__(
        self,
        tools: AgentToolService,
        model_factory: Callable[[], Any],
        *,
        model_id: str,
        read_timeout: float,
    ) -> None:
        self._tools = tools
        self._model_factory = model_factory
        self._model_id = model_id
        self._read_timeout = read_timeout

    def invoke(self, session_id: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        from found_agent.config import AGENT_VERSION
        from found_agent.run import RunRequest, run_investigation

        request = RunRequest.model_validate(payload)
        events: queue.Queue[Any] = queue.Queue()

        def work() -> None:
            async def go() -> None:
                async for event in run_investigation(
                    request,
                    self._model_factory(),
                    local_tools(self._tools),
                    model_id=self._model_id,
                    agent_version=AGENT_VERSION,
                ):
                    events.put(event)

            try:
                asyncio.run(go())
            except Exception as err:  # noqa: BLE001 - surfaced to the runner below
                events.put(err)
            finally:
                events.put(_DONE)

        # A daemon thread: if the runner stops reading at its deadline, the agent's own
        # guard ends the loop and the thread dies with the process.
        threading.Thread(target=work, name=f"agent-{session_id}", daemon=True).start()
        while True:
            try:
                item = events.get(timeout=self._read_timeout)
            except queue.Empty:
                raise AgentTimeout() from None
            if item is _DONE:
                return
            if isinstance(item, Exception):
                raise AgentUnavailable(type(item).__name__) from item
            yield item
