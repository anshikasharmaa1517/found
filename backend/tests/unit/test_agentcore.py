import json

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from found_core.adapters.agentcore import AgentCoreInvoker, parse_sse
from found_core.adapters.sqs_queue import SqsInvestigationQueue
from found_core.ports.agent import AgentTimeout, AgentUnavailable


class Body:
    def __init__(self, lines, error=None):
        self.lines = lines
        self.error = error

    def iter_lines(self):
        yield from self.lines
        if self.error:
            raise self.error


class Client:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error
        self.calls = []

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"response": self.body, "statusCode": 200}


def test_parse_sse_reads_data_lines_only():
    lines = [
        b'data: {"type": "start"}',
        b"",
        b": keepalive",
        b"data: not json",
        b"data: [1, 2]",
        b'data:{"type":"done"}',
    ]
    assert list(parse_sse(iter(lines))) == [{"type": "start"}, {"type": "done"}]


def test_invoker_sends_ids_only_and_streams_events():
    client = Client(Body([b'data: {"type": "step"}', b'data: {"type": "done"}']))
    invoker = AgentCoreInvoker(client, "arn:runtime")
    events = list(invoker.invoke("s" * 33, {"investigation_id": "inv_1"}))
    assert events == [{"type": "step"}, {"type": "done"}]
    call = client.calls[0]
    assert call["agentRuntimeArn"] == "arn:runtime" and call["runtimeSessionId"] == "s" * 33
    assert json.loads(call["payload"]) == {"investigation_id": "inv_1"}
    assert call["accept"] == "text/event-stream"


def test_invoker_maps_errors():
    denied = ClientError({"Error": {"Code": "AccessDeniedException"}}, "InvokeAgentRuntime")
    with pytest.raises(AgentUnavailable, match="ClientError"):
        list(AgentCoreInvoker(Client(error=denied), "arn").invoke("s" * 33, {}))
    slow = Body([b'data: {"type": "start"}'], ReadTimeoutError(endpoint_url="https://x"))
    with pytest.raises(AgentTimeout):
        list(AgentCoreInvoker(Client(slow), "arn").invoke("s" * 33, {}))


def test_queue_message_names_only_the_investigation():
    class Sqs:
        def __init__(self):
            self.sent = []

        def send_message(self, **kwargs):
            self.sent.append(kwargs)

    sqs = Sqs()
    SqsInvestigationQueue(sqs, "https://queue").send("inv_1")
    assert sqs.sent == [
        {"QueueUrl": "https://queue", "MessageBody": '{"investigation_id": "inv_1"}'}
    ]
