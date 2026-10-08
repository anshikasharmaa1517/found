import asyncio
import json
from types import SimpleNamespace

import httpx
from botocore.credentials import Credentials

from found_agent import app as app_module
from found_agent.config import AgentConfig
from found_agent.gateway import SigV4HttpxAuth
from found_agent.guard import RunGuard
from found_agent.steps import base_tool_name, redact_input, result_payload, summarize_tool


def test_tool_names_and_redaction():
    assert base_tool_name("found-tools___get_report") == "get_report"
    assert base_tool_name("get_report") == "get_report"
    assert redact_input({"investigation_id": "inv_1", "claim_id": "c"}) == {"claim_id": "c"}
    big = redact_input({"summary": "x" * 5000})
    assert big["truncated"] and len(big["preview"]) <= 2048


def test_result_payload_reads_the_first_text_block():
    assert result_payload({"content": [{"text": json.dumps({"ok": True})}]}) == {"ok": True}
    assert result_payload({"content": [{"text": "plain words"}]}) is None
    assert result_payload(None) is None


def test_summaries():
    assert summarize_tool("list_mentioned_sources", {"ok": True, "sources": []}) == "0 sources"
    assert (
        summarize_tool(
            "find_reports_by_source", {"ok": True, "source": {"name": "Hospital"}, "reports": [{}]}
        )
        == "1 report from Hospital"
    )
    assert summarize_tool("search_people", {"ok": True, "people": [{}, {}]}) == "2 matches"
    assert summarize_tool("get_report", {"ok": False, "error": {"code": "TOOL_CAP"}}) == (
        "Refused: TOOL_CAP"
    )
    assert summarize_tool("get_report", None) == "No structured result"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_wall_clock_stops_the_next_model_call():
    clock = Clock()
    guard = RunGuard("inv_1", max_turns=6, wall_clock_seconds=120, clock=clock)
    first = SimpleNamespace(cancel=False)
    guard.before_model(first)
    assert first.cancel is False and guard.model_calls == 1
    clock.t = 121
    late = SimpleNamespace(cancel=False)
    guard.before_model(late)
    assert late.cancel and guard.stop_reason == "WALL_CLOCK"
    assert guard.drain()[-1] == {"kind": "GUARD", "output_summary": "Stopped: the wall clock limit"}


class Session:
    def get_credentials(self):
        return Credentials("AKIDEXAMPLE", "secret", "token")


def test_gateway_requests_are_signed():
    request = httpx.Request("POST", "https://gw.example/mcp", content=b'{"jsonrpc":"2.0"}')
    signed = next(SigV4HttpxAuth(Session(), "ap-south-1").auth_flow(request))
    auth = signed.headers["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/ap-south-1/bedrock-agentcore/aws4_request" in auth
    assert signed.headers["X-Amz-Security-Token"] == "token"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "model-a")
    monkeypatch.setenv("GATEWAY_URL", "https://gw.example/mcp")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    config = AgentConfig.from_env()
    assert (config.model_id, config.guardrail_id) == ("model-a", None)
    model = app_module.bedrock_model(config, 512)
    settings = model.get_config()
    assert settings["temperature"] == 0.0 and settings["max_tokens"] == 512
    assert "guardrail_id" not in settings


def test_entrypoint_refuses_a_bad_payload():
    async def collect():
        return [e async for e in app_module.investigate({"claim_id": "x"}, None)]

    assert asyncio.run(collect()) == [
        {
            "type": "done",
            "finding_recorded": False,
            "stop_reason": "ERROR",
            "error_code": "BAD_REQUEST",
        }
    ]
