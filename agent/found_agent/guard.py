"""Hooks that bound one run and record its steps (design Sections 9.8 and 9.9).

- Every tool call gets this run's `investigation_id`, whatever the model wrote.
- Only the known tools may run.
- The model gets at most `max_turns` calls, and none after the finding is recorded.
- No model call starts after the wall clock deadline. The runner stops the run outright
  at the same limit; this check only ends it cleanly between calls.

The tools Lambda enforces the tool cap and validates the finding on its side as well;
these hooks keep a misbehaving model from spending turns it does not need.
"""

import time
from collections.abc import Callable
from typing import Any

from strands.hooks import (
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from found_agent.steps import (
    ALLOWED_TOOLS,
    base_tool_name,
    clip,
    redact_input,
    result_payload,
    summarize_tool,
)

FINDING_RECORDED = "FINDING_RECORDED"
TURN_LIMIT = "TURN_LIMIT"
WALL_CLOCK = "WALL_CLOCK"


class RunGuard(HookProvider):
    def __init__(
        self,
        investigation_id: str,
        max_turns: int,
        wall_clock_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.investigation_id = investigation_id
        self.max_turns = max_turns
        self.model_calls = 0
        self.tool_calls = 0
        self.finding_recorded = False
        self.stop_reason: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self._clock = clock
        self._deadline = None if wall_clock_seconds is None else clock() + wall_clock_seconds
        self._steps: list[dict[str, Any]] = []
        self._model_started: float | None = None
        self._call_usage: dict[str, int] | None = None
        self._tool_started: dict[str, float] = {}
        self._refused: set[str] = set()

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(AfterModelCallEvent, self.after_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def drain(self) -> list[dict[str, Any]]:
        steps, self._steps = self._steps, []
        return steps

    def note_usage(self, usage: dict[str, Any]) -> None:
        """Token counts the model reported for the call in progress."""
        self._call_usage = {
            "input_tokens": int(usage.get("inputTokens", 0)),
            "output_tokens": int(usage.get("outputTokens", 0)),
        }

    def error(self, code: str, message: str) -> None:
        self._steps.append({"kind": "ERROR", "error_code": code, "output_summary": clip(message)})

    def before_model(self, event: BeforeModelCallEvent) -> None:
        if self.finding_recorded:
            self.stop_reason = FINDING_RECORDED
            event.cancel = "The finding is recorded. The investigation is over."
            return
        if self.model_calls >= self.max_turns:
            self._stop(event, TURN_LIMIT, f"the limit of {self.max_turns} model turns")
            return
        if self._deadline is not None and self._clock() >= self._deadline:
            self._stop(event, WALL_CLOCK, "the wall clock limit")
            return
        self.model_calls += 1
        self._model_started = self._clock()
        self._call_usage = None

    def _stop(self, event: BeforeModelCallEvent, reason: str, limit: str) -> None:
        self.stop_reason = reason
        event.cancel = f"Stopped by {limit}."
        self._steps.append({"kind": "GUARD", "output_summary": f"Stopped: {limit}"})

    def after_model(self, event: AfterModelCallEvent) -> None:
        if self._model_started is None:
            return
        duration_ms = int((self._clock() - self._model_started) * 1000)
        self._model_started = None
        usage = self._call_usage or {"input_tokens": 0, "output_tokens": 0}
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        step: dict[str, Any] = {"kind": "MODEL", "duration_ms": duration_ms, **usage}
        if event.exception is not None or event.stop_response is None:
            step["kind"] = "ERROR"
            step["error_code"] = "MODEL_ERROR"
            step["output_summary"] = clip(type(event.exception).__name__)
            self._steps.append(step)
            return
        content = event.stop_response.message.get("content") or []
        requested = [
            base_tool_name(block["toolUse"]["name"]) for block in content if "toolUse" in block
        ]
        if requested:
            step["output_summary"] = "Requested " + ", ".join(requested)
        else:
            text = " ".join(block["text"] for block in content if "text" in block).strip()
            step["output_summary"] = clip(text or "No text", 300)
        step["stop_reason"] = str(event.stop_response.stop_reason)
        self._steps.append(step)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        tool_use = event.tool_use
        name = base_tool_name(str(tool_use.get("name", "")))
        if name not in ALLOWED_TOOLS or self.finding_recorded:
            self._refused.add(tool_use["toolUseId"])
            event.cancel_tool = f"The tool {name} is not available."
            self._steps.append(
                {"kind": "GUARD", "tool": name, "output_summary": f"Refused tool {name}"}
            )
            return
        arguments = dict(tool_use.get("input") or {})
        arguments["investigation_id"] = self.investigation_id
        event.tool_use = {**tool_use, "input": arguments}
        self.tool_calls += 1
        self._tool_started[tool_use["toolUseId"]] = self._clock()

    def after_tool(self, event: AfterToolCallEvent) -> None:
        tool_use_id = event.tool_use["toolUseId"]
        if tool_use_id in self._refused:
            return
        started = self._tool_started.pop(tool_use_id, self._clock())
        name = base_tool_name(str(event.tool_use.get("name", "")))
        payload = result_payload(event.result)
        step: dict[str, Any] = {
            "kind": "TOOL",
            "tool": name,
            "input": redact_input(event.tool_use.get("input")),
            "output_summary": summarize_tool(name, payload),
            "duration_ms": int((self._clock() - started) * 1000),
        }
        if event.exception is not None:
            step["kind"] = "ERROR"
            step["error_code"] = "TOOL_ERROR"
            step["output_summary"] = clip(type(event.exception).__name__)
        elif name == "record_finding" and payload and payload.get("ok"):
            self.finding_recorded = True
        self._steps.append(step)
