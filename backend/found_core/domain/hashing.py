"""Canonical hashing for idempotency and fingerprints."""

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_hash(obj: Any) -> str:
    return "sha256:" + sha256_hex(canonical_json(obj))
