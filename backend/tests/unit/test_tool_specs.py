import json
from pathlib import Path

from found_core.tools.arguments import TOOL_ARGS, gateway_schema, gateway_specs

SPECS = Path(__file__).resolve().parents[2] / "found_core" / "tools" / "specs.json"
GATEWAY_KEYS = {"type", "description", "properties", "required", "items"}


def test_committed_specs_match_the_code():
    # Regenerate with: python -m found_core.tools.arguments
    assert json.loads(SPECS.read_text(encoding="utf-8")) == gateway_specs()


def _keys(node):
    yield set(node)
    for child in (node.get("properties") or {}).values():
        yield from _keys(child)
    if "items" in node:
        yield from _keys(node["items"])


def test_specs_use_only_what_gateway_accepts():
    specs = gateway_specs()
    assert [s["name"] for s in specs] == list(TOOL_ARGS)
    for spec in specs:
        assert set(spec) == {"name", "description", "inputSchema"}
        for keys in _keys(spec["inputSchema"]):
            assert keys <= GATEWAY_KEYS


def test_allowed_values_and_limits_move_into_the_description():
    schema = gateway_schema(
        {"type": "string", "description": "Label.", "enum": ["A", "B"], "maxLength": 9}
    )
    assert schema == {"type": "string", "description": "Label. One of: A, B. At most 9 characters."}
    limit = gateway_schema({"type": "integer", "minimum": 1, "maximum": 10})
    assert limit["description"] == "At least 1. At most 10."
