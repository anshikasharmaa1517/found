import pytest

from found_core import container
from handlers import agent_tools


class ClientContext:
    def __init__(self, custom):
        self.custom = custom


class Context:
    function_name = "agent_tools"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:agent_tools"
    aws_request_id = "req-1"

    def __init__(self, tool=None):
        self.client_context = ClientContext({"bedrockAgentCoreToolName": tool} if tool else None)


class FakeTools:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "get_report":
            return {"ok": True, "tool_calls_left": 7}
        return {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": "no"}}


@pytest.fixture
def tools(monkeypatch):
    fake = FakeTools()
    monkeypatch.setattr(container, "agent_tool_service", lambda: fake)
    return fake


@pytest.mark.parametrize(
    "raw, name",
    [("found-tools___get_report", "get_report"), ("get_report", "get_report"), (None, "")],
)
def test_tool_name_drops_the_target_prefix(raw, name):
    assert agent_tools.tool_name(Context(raw)) == name


def test_handler_passes_arguments_through(tools):
    args = {"investigation_id": "inv_1", "claim_id": "clm_1"}
    result = agent_tools.handler(args, Context("found-tools___get_report"))
    assert result == {"ok": True, "tool_calls_left": 7}
    assert tools.calls == [("get_report", args)]


def test_refusals_are_returned_as_data(tools):
    result = agent_tools.handler({"investigation_id": "inv_1"}, Context("t___drop_table"))
    assert result["error"]["code"] == "UNKNOWN_TOOL"
