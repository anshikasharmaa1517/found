"""AgentCore Runtime invoker. The runtime streams events as server-sent events."""

import json
from collections.abc import Iterator
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

from found_core.ports.agent import AgentTimeout, AgentUnavailable

_DATA = b"data:"


def parse_sse(lines: Iterator[bytes]) -> Iterator[dict[str, Any]]:
    """JSON objects from `data:` lines. Comments, blank lines and non-objects are skipped."""
    for raw in lines:
        line = raw.strip()
        if not line.startswith(_DATA):
            continue
        try:
            event = json.loads(line[len(_DATA) :])
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


class AgentCoreInvoker:
    def __init__(self, client: Any, runtime_arn: str) -> None:
        self._client = client
        self._runtime_arn = runtime_arn

    def invoke(self, session_id: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        try:
            resp = self._client.invoke_agent_runtime(
                agentRuntimeArn=self._runtime_arn,
                runtimeSessionId=session_id,
                contentType="application/json",
                accept="text/event-stream",
                payload=json.dumps(payload).encode(),
            )
            yield from parse_sse(resp["response"].iter_lines())
        except ReadTimeoutError as err:
            raise AgentTimeout() from err
        except (BotoCoreError, ClientError) as err:
            raise AgentUnavailable(type(err).__name__) from err
