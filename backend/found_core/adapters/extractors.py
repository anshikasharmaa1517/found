"""Candidate extraction with a forced `emit_candidates` tool call (design Section 9.10).

Two ways to reach the model: Bedrock Converse, or the OpenAI-compatible bedrock-mantle
endpoint with a Bedrock API key (for accounts where Converse is not allowed). Either way
the model only proposes; `validate_candidates` decides what is kept.
"""

import json
import urllib.error
import urllib.request
from typing import Any

from found_core.domain.intake import EMIT_CANDIDATES_SCHEMA, extraction_prompt
from found_core.ports.intake import ExtractionFailed

TOOL = "emit_candidates"
TOOL_DESCRIPTION = "Return the candidate claims found in the report text."
MAX_TOKENS = 2000


def mantle_url(region: str) -> str:
    """The OpenAI-compatible bedrock-mantle endpoint for chat completions."""
    return f"https://bedrock-mantle.{region}.api.aws/v1"


def _candidates(arguments: Any) -> list[Any]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            raise ExtractionFailed("MODEL_INVALID_JSON") from None
    if not isinstance(arguments, dict) or not isinstance(arguments.get("candidates"), list):
        raise ExtractionFailed("MODEL_INVALID_OUTPUT")
    return arguments["candidates"]


def _user_message(text: str) -> str:
    return f"<text_untrusted>\n{text}\n</text_untrusted>"


class ConverseExtractor:
    def __init__(self, client: Any, model_id: str) -> None:
        self._client = client
        self._model_id = model_id

    def extract(self, text: str) -> list[Any]:
        try:
            resp = self._client.converse(
                modelId=self._model_id,
                system=[{"text": extraction_prompt()}],
                messages=[{"role": "user", "content": [{"text": _user_message(text)}]}],
                inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
                toolConfig={
                    "tools": [
                        {
                            "toolSpec": {
                                "name": TOOL,
                                "description": TOOL_DESCRIPTION,
                                "inputSchema": {"json": EMIT_CANDIDATES_SCHEMA},
                            }
                        }
                    ],
                    "toolChoice": {"tool": {"name": TOOL}},
                },
            )
        except Exception as err:  # noqa: BLE001 - any provider error fails this job
            raise ExtractionFailed(f"MODEL_{type(err).__name__}") from err
        for block in resp.get("output", {}).get("message", {}).get("content", []):
            use = block.get("toolUse")
            if use and use.get("name") == TOOL:
                return _candidates(use.get("input"))
        raise ExtractionFailed("MODEL_NO_TOOL_CALL")


class MantleExtractor:
    """Chat completions on bedrock-mantle, authenticated with a Bedrock API key."""

    def __init__(self, base_url: str, api_key: str, model_id: str, timeout: float = 60) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._model_id = model_id
        self._timeout = timeout

    def request_body(self, text: str) -> dict[str, Any]:
        return {
            "model": self._model_id,
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS,
            "messages": [
                {"role": "system", "content": extraction_prompt()},
                {"role": "user", "content": _user_message(text)},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": TOOL,
                        "description": TOOL_DESCRIPTION,
                        "parameters": EMIT_CANDIDATES_SCHEMA,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": TOOL}},
        }

    def extract(self, text: str) -> list[Any]:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(self.request_body(text)).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:  # noqa: S310
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            raise ExtractionFailed(f"MODEL_HTTP_{err.code}") from err
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            raise ExtractionFailed("MODEL_UNREACHABLE") from err
        return parse_chat_completion(payload)


def parse_chat_completion(payload: dict[str, Any]) -> list[Any]:
    for choice in payload.get("choices", []):
        for call in choice.get("message", {}).get("tool_calls") or []:
            function = call.get("function", {})
            if function.get("name") == TOOL:
                return _candidates(function.get("arguments"))
    raise ExtractionFailed("MODEL_NO_TOOL_CALL")
