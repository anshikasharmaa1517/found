"""Runs one queued investigation on the agent (design Sections 5.2 step 3, 9.8, 10.4).

The runner owns the run's lifecycle around the agent: QUEUED to RUNNING, every step
stored in order, the wall clock, the monthly model call cap, and FAILED with a reason
whenever the agent ends without a finding. The finding itself is written only by
`record_finding` in the tools Lambda, so a run the runner has failed can no longer
record one (that write requires RUNNING).

A message is redelivered only after a runner crash. Budget is reserved once at start
and steps may be half written by then, so a redelivered run is failed, not repeated.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from found_core.domain.enums import InvestigationStatus, StepKind
from found_core.domain.investigation import (
    TERMINAL_STATUSES,
    InvestigationConfig,
    budget_period,
)
from found_core.domain.models import STEP_FIELD_MAX, Investigation, InvestigationStep
from found_core.ports.agent import AgentInvoker, AgentTimeout, AgentUnavailable
from found_core.ports.budget import BudgetLedger
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository

S = InvestigationStatus

# Why the agent stopped, as it reports it, mapped to the stored failure reason.
STOP_REASONS = {
    "TURN_LIMIT": "TURN_LIMIT",
    "WALL_CLOCK": "TIMEOUT",
    "END_TURN": "NO_FINDING",
    "FINDING_RECORDED": "NO_FINDING",
}


@dataclass(frozen=True)
class RunResult:
    investigation_id: str
    status: InvestigationStatus | None
    steps: int = 0
    skipped_reason: str | None = None
    failure_reason: str | None = None


def session_id(investigation_id: str) -> str:
    """Runtime session per run. AgentCore needs at least 33 characters."""
    return f"found-run-{investigation_id}".ljust(33, "0")


def _clip(text: Any, limit: int = STEP_FIELD_MAX) -> str | None:
    if text is None:
        return None
    value = str(text)
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class _Run:
    """Mutable state of one run while its stream is read."""

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        self.seq = 0
        self.failure: str | None = None
        self.done: dict[str, Any] | None = None


class InvestigationRunner:
    def __init__(
        self,
        repo: FoundRepository,
        ledger: BudgetLedger,
        invoker: AgentInvoker,
        config: InvestigationConfig,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repo = repo
        self._ledger = ledger
        self._invoker = invoker
        self._config = config
        self._clock = clock or SystemClock()
        self._monotonic = monotonic

    def run(self, investigation_id: str) -> RunResult:
        current = self._repo.get_investigation(investigation_id)
        if current is None:
            # Only a demo reset deletes runs; the message outlived its investigation.
            return RunResult(investigation_id, None, skipped_reason="NOT_FOUND")
        if current.status in TERMINAL_STATUSES:
            return RunResult(investigation_id, current.status, skipped_reason="ALREADY_DONE")
        if current.status == S.RUNNING:
            failed = self._fail(current, S.RUNNING, "RUNNER_INTERRUPTED")
            self._repo.release_run_lock(current.claim_id, current.id)
            return RunResult(
                investigation_id,
                failed.status if failed else None,
                skipped_reason="REDELIVERED",
                failure_reason="RUNNER_INTERRUPTED",
            )

        running = self._repo.update_investigation_if(
            investigation_id, S.QUEUED, {"status": S.RUNNING, "started_at": self._clock.now()}
        )
        if running is None:
            return RunResult(investigation_id, None, skipped_reason="NOT_QUEUED")

        state = _Run(running)
        try:
            self._read(state)
        finally:
            self._finish(state)
            self._repo.release_run_lock(running.claim_id, running.id)
        final = self._repo.get_investigation(investigation_id)
        return RunResult(
            investigation_id,
            final.status if final else None,
            steps=state.seq,
            failure_reason=final.failure_reason if final else state.failure,
        )

    def fail_queued(self, investigation_id: str, reason: str) -> bool:
        """Last resort after the final delivery attempt failed: never leave a run QUEUED."""
        current = self._repo.get_investigation(investigation_id)
        if current is None or current.status not in (S.QUEUED, S.RUNNING):
            return False
        failed = self._fail(current, current.status, reason)
        self._repo.release_run_lock(current.claim_id, current.id)
        return failed is not None

    def _read(self, state: _Run) -> None:
        inv = state.investigation
        payload = {
            "investigation_id": inv.id,
            "claim_id": inv.claim_id,
            "incident_id": inv.incident_id,
            "limits": self._config.limits(),
        }
        deadline = self._monotonic() + self._config.wall_clock_seconds
        events = self._invoker.invoke(session_id(inv.id), payload)
        try:
            for event in events:
                if self._monotonic() >= deadline:
                    self._guard(state, "TIMEOUT", "Stopped: the wall clock limit")
                    return
                if not self._handle(state, event):
                    return
        except AgentTimeout:
            self._guard(state, "TIMEOUT", "Stopped: the agent stopped responding")
        except AgentUnavailable as err:
            self._step(
                state, StepKind.ERROR, output_summary=str(err), error_code="AGENT_UNAVAILABLE"
            )
            state.failure = "AGENT_UNAVAILABLE"
        finally:
            # Stop reading the agent's stream; the agent's own guard ends its session.
            close = getattr(events, "close", None)
            if close is not None:
                close()

    def _handle(self, state: _Run, event: dict[str, Any]) -> bool:
        """Apply one event. False stops reading the stream."""
        inv = state.investigation
        match event.get("type"):
            case "start":
                expected = (inv.model_id, inv.prompt_version, inv.agent_version)
                got = tuple(event.get(k) for k in ("model_id", "prompt_version", "agent_version"))
                if got != expected:
                    # The stored labels must describe what really ran (product rule 7).
                    self._guard(state, "VERSION_MISMATCH", "Stopped: the agent runs other versions")
                    return False
            case "step":
                step = event.get("step")
                if isinstance(step, dict) and not self._store_step(state, step):
                    return False
            case "done":
                state.done = event
                return False
        return True

    def _store_step(self, state: _Run, raw: dict[str, Any]) -> bool:
        try:
            kind = StepKind(raw.get("kind"))
        except ValueError:
            kind = StepKind.ERROR
        tool_input = raw.get("input")
        self._step(
            state,
            kind,
            tool_name=_clip(raw.get("tool"), 64),
            input_json=_clip(json.dumps(tool_input, sort_keys=True, default=str))
            if tool_input is not None
            else None,
            output_summary=_clip(raw.get("output_summary")),
            duration_ms=_int(raw.get("duration_ms")),
            input_tokens=_int(raw.get("input_tokens")),
            output_tokens=_int(raw.get("output_tokens")),
            error_code=_clip(raw.get("error_code"), 64),
        )
        if kind == StepKind.MODEL:
            period = budget_period(state.investigation.queued_at)
            if not self._ledger.count_model_call(period, self._config.model_call_cap):
                self._guard(state, "MODEL_CALL_CAP", "Stopped: the monthly model call budget")
                return False
        return True

    def _guard(self, state: _Run, reason: str, summary: str) -> None:
        self._step(state, StepKind.GUARD, output_summary=summary)
        state.failure = reason

    def _step(self, state: _Run, kind: StepKind, **fields: Any) -> None:
        state.seq += 1
        inv = state.investigation
        self._repo.put_investigation_step(
            InvestigationStep(
                investigation_id=inv.id,
                incident_id=inv.incident_id,
                seq=state.seq,
                kind=kind,
                created_at=self._clock.now(),
                **fields,
            )
        )

    def _finish(self, state: _Run) -> None:
        inv = state.investigation
        done = state.done or {}
        usage = done.get("usage") if isinstance(done.get("usage"), dict) else {}
        input_tokens = _int(usage.get("input_tokens")) or 0
        output_tokens = _int(usage.get("output_tokens")) or 0
        if input_tokens or output_tokens:
            self._ledger.add_tokens(budget_period(inv.queued_at), input_tokens, output_tokens)

        current = self._repo.get_investigation(inv.id)
        if current is None:
            return
        if current.status == S.RUNNING:
            reason = state.failure
            if reason is None:
                stop = str(done.get("stop_reason") or "")
                reason = done.get("error_code") or STOP_REASONS.get(stop, "NO_FINDING")
            current = self._fail(current, S.RUNNING, str(reason)) or current
        # Usage is labeled on whatever state the run ended in; the status stays as is.
        changes: dict[str, Any] = {
            "model_calls": _int(done.get("model_calls")) or 0,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usage_source": str(usage.get("usage_source") or "provider"),
        }
        self._repo.update_investigation_if(inv.id, current.status, changes)

    def _fail(
        self, current: Investigation, expected: InvestigationStatus, reason: str
    ) -> Investigation | None:
        return self._repo.update_investigation_if(
            current.id,
            expected,
            {"status": S.FAILED, "failure_reason": reason, "finished_at": self._clock.now()},
        )
