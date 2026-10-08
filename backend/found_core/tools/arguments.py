"""Arguments of each agent tool, and the tool specs Gateway publishes to the agent.

Every tool takes `investigation_id`. The agent runtime overwrites it from the session
before each call, so the model cannot pick another run. Unknown arguments are refused.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from found_core.domain.findings import FindingInput


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    investigation_id: str = Field(min_length=1, max_length=64)


class ClaimArgs(_Args):
    claim_id: str = Field(min_length=1, max_length=64)


class SourceReportsArgs(_Args):
    source_id: str = Field(min_length=1, max_length=64)
    subject_id: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=10, ge=1, le=10)


class TimelineArgs(_Args):
    person_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=20)


class SearchPeopleArgs(_Args):
    name: str = Field(min_length=2, max_length=120)
    age: int | None = Field(default=None, ge=0, le=120)


class RecordFindingArgs(_Args, FindingInput):
    pass


TOOL_ARGS: dict[str, type[_Args]] = {
    "get_report": ClaimArgs,
    "list_mentioned_sources": ClaimArgs,
    "find_reports_by_source": SourceReportsArgs,
    "get_person_timeline": TimelineArgs,
    "search_people": SearchPeopleArgs,
    "record_finding": RecordFindingArgs,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_report": "Read one report: its text, type, source, reported time and subject.",
    "list_mentioned_sources": "List the sources a report names in its text.",
    "find_reports_by_source": (
        "List a source's reports, latest first, optionally about one subject (at most 10)."
    ),
    "get_person_timeline": "List the reports about one person (at most 20, latest last).",
    "search_people": "Find people in this incident by name, optionally near an age.",
    "record_finding": (
        "Record the one finding of this investigation: attribution, referenced source, "
        "comparison, a short summary and verbatim citations. Returns errors to correct."
    ),
}


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """Replace each `$ref` with its definition. Gateway schemas take no references."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        options = node.get("anyOf")
        if options is not None:
            # An optional field is simply left out of `required`.
            present = [o for o in options if o.get("type") != "null"]
            if len(present) == 1:
                rest = {k: v for k, v in node.items() if k not in ("anyOf", "default")}
                return _inline({**present[0], **rest}, defs)
        return {
            k: _inline(v, defs)
            for k, v in node.items()
            if k not in ("$defs", "title") and not (k == "default" and v is None)
        }
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def input_schema(args: type[BaseModel]) -> dict[str, Any]:
    schema = args.model_json_schema()
    return _inline(schema, schema.get("$defs", {}))


def tool_specs() -> list[dict[str, Any]]:
    """Gateway Lambda target tool schema: name, description and JSON input schema."""
    return [
        {"name": name, "description": TOOL_DESCRIPTIONS[name], "inputSchema": input_schema(args)}
        for name, args in TOOL_ARGS.items()
    ]
