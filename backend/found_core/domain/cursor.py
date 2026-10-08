"""Pagination: page limits and opaque cursors (design Section 7.1).

A cursor is a base64 JSON position plus an HMAC over the position and the scope it was
issued for, so clients cannot forge positions or replay a cursor on another listing.
"""

import base64
import hashlib
import hmac
import json
from typing import Any

from found_core.domain.errors import BadRequest


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class CursorCodec:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("cursor key must be at least 32 bytes")
        self._key = key

    def _sign(self, scope: str, payload: bytes) -> bytes:
        return hmac.new(self._key, scope.encode() + b"\x00" + payload, hashlib.sha256).digest()

    def encode(self, scope: str, position: dict[str, Any]) -> str:
        payload = json.dumps(position, separators=(",", ":"), sort_keys=True).encode()
        return f"{_b64(payload)}.{_b64(self._sign(scope, payload))}"

    def decode(self, scope: str, token: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".")
            payload = _unb64(body)
            valid = hmac.compare_digest(_unb64(signature), self._sign(scope, payload))
            position = json.loads(payload) if valid else None
        except (ValueError, UnicodeDecodeError):
            position = None
        if not isinstance(position, dict):
            raise BadRequest("Cursor is invalid.")
        return position


DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def parse_limit(raw: str | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        raise BadRequest("limit must be a whole number.") from None
    if not 1 <= limit <= MAX_LIMIT:
        raise BadRequest(f"limit must be between 1 and {MAX_LIMIT}.")
    return limit
