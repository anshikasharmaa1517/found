"""Compact, redacted step records for the runner to store and stream.

Steps never carry report text: tool results are summarized from their structured
fields, so untrusted text is not copied into the trace. Inputs and summaries are capped
at 2 KB each.
"""

import json
from typing import Any

MAX_FIELD = 2048
TARGET_DELIMITER = "___"

ALLOWED_TOOLS = frozenset(
    {
        "get_report",
        "list_mentioned_sources",
        "find_reports_by_source",
        "get_person_timeline",
        "search_people",
        "record_finding",
    }
)


def base_tool_name(name: str) -> str:
    """Gateway names tools `{target}___{tool}`; steps use the plain tool name."""
    return name.rsplit(TARGET_DELIMITER, 1)[-1]


def clip(text: str, limit: int = MAX_FIELD) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def redact_input(tool_input: dict[str, Any] | None) -> dict[str, Any]:
    shown = {k: v for k, v in (tool_input or {}).items() if k != "investigation_id"}
    text = json.dumps(shown, ensure_ascii=False, default=str)
    if len(text) <= MAX_FIELD:
        return shown
    return {"truncated": True, "preview": clip(text, MAX_FIELD - 100)}


def result_payload(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The tool's JSON body, from the first text block of an MCP tool result."""
    for block in (result or {}).get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _count(items: Any, noun: str, plural: str | None = None) -> str:
    n = len(items) if isinstance(items, list) else 0
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"


def summarize_tool(tool: str, payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "No structured result"
    if not payload.get("ok"):
        error = payload.get("error") or {}
        codes = sorted({e.get("code", "") for e in error.get("errors") or []} - {""})
        detail = f" ({', '.join(codes)})" if codes else ""
        return clip(f"Refused: {error.get('code', 'UNKNOWN')}{detail}")
    match tool:
        case "get_report":
            report = payload.get("report") or {}
            return clip(f"Read report {report.get('claim_id')} from {report.get('source')}")
        case "list_mentioned_sources":
            sources = payload.get("sources") or []
            names = ", ".join(str(s.get("name")) for s in sources)
            return clip(f"{_count(sources, 'source')}" + (f": {names}" if names else ""))
        case "find_reports_by_source":
            source = (payload.get("source") or {}).get("name")
            return clip(f"{_count(payload.get('reports'), 'report')} from {source}")
        case "get_person_timeline":
            person = (payload.get("person") or {}).get("name")
            return clip(f"{_count(payload.get('reports'), 'report')} about {person}")
        case "search_people":
            return _count(payload.get("people"), "match", "matches")
        case "record_finding":
            return f"Finding recorded: {payload.get('status')}"
    return "Done"
