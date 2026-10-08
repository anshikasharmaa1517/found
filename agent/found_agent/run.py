"""One provenance run: validate the request, drive the agent, stream compact events.

The payload holds only IDs and limits, never instructions. IDs are checked against
their formats before they enter the task text. Events:

- `{"type": "start", ...}` with the versions that define the run,
- `{"type": "step", "step": {...}}` for each model call, tool call, guard or error,
- `{"type": "done", ...}` once, with counts, token usage and why the run ended.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from strands import Agent
from strands.models.model import Model

from found_agent.guard import RunGuard
from found_agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT

END_TURN = "END_TURN"
ERROR = "ERROR"


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    max_tool_calls: int = Field(default=8, ge=1, le=20)
    max_model_turns: int = Field(default=6, ge=1, le=12)
    wall_clock_seconds: int = Field(default=120, ge=10, le=300)
    max_output_tokens: int = Field(default=512, ge=64, le=2048)


class RunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: str = Field(pattern=r"^inv_[0-9A-Za-z]{1,40}$")
    claim_id: str = Field(pattern=r"^clm_[0-9A-Za-z]{1,40}$")
    incident_id: str = Field(pattern=r"^inc_[0-9A-Za-z_]{1,40}$")
    limits: Limits = Limits()


def task(request: RunRequest) -> str:
    return (
        f"Investigate claim {request.claim_id} in incident {request.incident_id}. "
        "Follow the procedure and record exactly one finding."
    )


def _usage(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    inner = event.get("event")
    if not isinstance(inner, dict):
        return None
    usage = (inner.get("metadata") or {}).get("usage")
    return usage if isinstance(usage, dict) else None


async def run_investigation(
    request: RunRequest,
    model: Model,
    tools: Sequence[Any],
    *,
    model_id: str,
    agent_version: str,
) -> AsyncIterator[dict[str, Any]]:
    guard = RunGuard(
        request.investigation_id,
        request.limits.max_model_turns,
        wall_clock_seconds=request.limits.wall_clock_seconds,
    )
    yield {
        "type": "start",
        "investigation_id": request.investigation_id,
        "model_id": model_id,
        "prompt_version": PROMPT_VERSION,
        "agent_version": agent_version,
    }
    error_code: str | None = None
    try:
        agent = Agent(
            model=model,
            tools=list(tools),
            system_prompt=SYSTEM_PROMPT,
            hooks=[guard],
            callback_handler=None,
            # A failed model call ends the run. It is never retried, so cost stays bounded.
            retry_strategy=None,
        )
        async for event in agent.stream_async(task(request)):
            usage = _usage(event)
            if usage is not None:
                guard.note_usage(usage)
            for step in guard.drain():
                yield {"type": "step", "step": step}
    except Exception as err:  # noqa: BLE001 - every failure must end in a done event
        error_code = "AGENT_ERROR"
        guard.error(error_code, type(err).__name__)
    for step in guard.drain():
        yield {"type": "step", "step": step}
    yield {
        "type": "done",
        "investigation_id": request.investigation_id,
        "finding_recorded": guard.finding_recorded,
        "stop_reason": ERROR if error_code else (guard.stop_reason or END_TURN),
        "error_code": error_code,
        "model_calls": guard.model_calls,
        "tool_calls": guard.tool_calls,
        "usage": {
            "input_tokens": guard.input_tokens,
            "output_tokens": guard.output_tokens,
            "usage_source": "provider",
        },
    }
