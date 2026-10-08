"""A scripted model and fake Gateway tools, so runs are tested without AWS."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from strands.models.model import Model
from strands.tools import PythonAgentTool

TARGET = "found-tools___"


class ScriptedModel(Model):
    """Plays one scripted turn per call: a list of ("tool", name, input) or ("text", str)."""

    def __init__(self, turns: list[list[tuple]], fail_on: int | None = None) -> None:
        self.turns = turns
        self.calls = 0
        self.fail_on = fail_on
        self.seen_messages: list[list[dict]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "stub"}

    def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs: Any):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.fail_on == self.calls:
            raise RuntimeError("model unavailable")
        turn = self.turns[self.calls - 1] if self.calls <= len(self.turns) else [("text", "Done.")]
        async for event in _events(turn, self.calls):
            yield event


async def _events(turn: list[tuple], call: int) -> AsyncIterator[dict[str, Any]]:
    yield {"messageStart": {"role": "assistant"}}
    uses_tool = False
    for n, block in enumerate(turn):
        if block[0] == "tool":
            uses_tool = True
            _, name, tool_input = block
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"name": TARGET + name, "toolUseId": f"t{call}_{n}"}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(tool_input)}}}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": block[1]}}}
        yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use" if uses_tool else "end_turn"}}
    yield {
        "metadata": {
            "usage": {
                "inputTokens": 100 * call,
                "outputTokens": 10,
                "totalTokens": 100 * call + 10,
            },
            "metrics": {"latencyMs": 1},
        }
    }


def gateway_tools(respond: Callable[[str, dict], dict]) -> tuple[list[PythonAgentTool], list]:
    """Tools named as Gateway names them. Each call is logged and answered by `respond`."""
    calls: list[tuple[str, dict]] = []
    names = [
        "get_report",
        "list_mentioned_sources",
        "find_reports_by_source",
        "get_person_timeline",
        "search_people",
        "record_finding",
        "delete_everything",
    ]

    def make(name: str) -> PythonAgentTool:
        def func(tool_use, **kwargs):
            calls.append((name, dict(tool_use["input"])))
            body = respond(name, tool_use["input"])
            return {
                "toolUseId": tool_use["toolUseId"],
                "status": "success",
                "content": [{"text": json.dumps(body)}],
            }

        spec = {
            "name": TARGET + name,
            "description": name,
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
        return PythonAgentTool(TARGET + name, spec, func)

    return [make(n) for n in names], calls
