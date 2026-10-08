from collections.abc import Iterator
from typing import Any, Protocol


class AgentTimeout(Exception):
    """The agent sent nothing for longer than the read timeout."""


class AgentUnavailable(Exception):
    """The agent could not be invoked or its stream broke."""


class AgentInvoker(Protocol):
    def invoke(self, session_id: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Start one run and yield its events (`start`, `step`, `done`) as they arrive."""
        ...
