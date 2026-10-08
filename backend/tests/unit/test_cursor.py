import base64
import json

import pytest

from found_core.domain.cursor import CursorCodec
from found_core.domain.errors import BadRequest

KEY = b"k" * 32


def test_round_trip():
    codec = CursorCodec(KEY)
    token = codec.encode("people:inc_1", {"n": "maya rawat", "i": "per_1"})
    assert codec.decode("people:inc_1", token) == {"n": "maya rawat", "i": "per_1"}


def test_cursor_is_bound_to_its_scope():
    codec = CursorCodec(KEY)
    token = codec.encode("timeline:per_1:asc", {"s": 3})
    with pytest.raises(BadRequest):
        codec.decode("timeline:per_2:asc", token)


def test_forged_position_is_rejected():
    codec = CursorCodec(KEY)
    token = codec.encode("people:inc_1", {"n": "a", "i": "per_1"})
    forged = base64.urlsafe_b64encode(json.dumps({"n": "z"}).encode()).rstrip(b"=").decode()
    with pytest.raises(BadRequest):
        codec.decode("people:inc_1", f"{forged}.{token.split('.')[1]}")


def test_other_key_is_rejected():
    token = CursorCodec(KEY).encode("s", {"s": 1})
    with pytest.raises(BadRequest):
        CursorCodec(b"x" * 32).decode("s", token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "!!!.???", "bnVsbA.AAAA"])
def test_garbage_is_bad_request(token):
    with pytest.raises(BadRequest):
        CursorCodec(KEY).decode("s", token)


def test_short_key_is_refused():
    with pytest.raises(ValueError):
        CursorCodec(b"short")
