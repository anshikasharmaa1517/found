"""Identifier helpers: type-prefixed ULIDs and deterministic source IDs."""

import hashlib
import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None, randomness: bytes | None = None) -> str:
    """Return a 26-character ULID: 48-bit millisecond time and 80 random bits."""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    rand = os.urandom(10) if randomness is None else randomness
    value = (ts << 80) | int.from_bytes(rand, "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"


def source_id(incident_id: str, name_norm: str) -> str:
    """Deterministic, so one organization name maps to one source per incident."""
    digest = hashlib.sha256(f"{incident_id}|{name_norm}".encode()).hexdigest()
    return f"src_{digest[:16]}"


def review_item_id(item_type: str, ref_id: str) -> str:
    """Deterministic, so a retried writer finds the item it already created."""
    digest = hashlib.sha256(f"{item_type}|{ref_id}".encode()).hexdigest()
    return f"rev_{digest[:16]}"
