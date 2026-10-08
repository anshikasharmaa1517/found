"""Text normalization, name tokens and deterministic source mention detection."""

import re
import unicodedata
from collections.abc import Iterable
from typing import Protocol

_NON_WORD = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")

MIN_MENTION_LENGTH = 4
MAX_MENTIONS = 8


class Named(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name_norm(self) -> str: ...


def normalize_text(text: str) -> str:
    """NFKC, casefold, punctuation to spaces, collapsed whitespace."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _SPACES.sub(" ", _NON_WORD.sub(" ", folded)).strip()


def name_tokens(name: str) -> list[str]:
    """Unique tokens of at least two characters, in order of appearance."""
    tokens: list[str] = []
    for token in normalize_text(name).split(" "):
        if len(token) >= 2 and token not in tokens:
            tokens.append(token)
    return tokens


def detect_mentions[T: Named](
    text: str, sources: Iterable[T], exclude_id: str | None = None
) -> list[T]:
    """Sources whose full normalized name appears as whole words in the text.

    Ordered by first appearance and capped at MAX_MENTIONS. No model is involved, so the
    set of sources the agent may name is always grounded in code.
    """
    haystack = f" {normalize_text(text)} "
    hits: list[tuple[int, T]] = []
    for source in sources:
        if source.id == exclude_id or len(source.name_norm) < MIN_MENTION_LENGTH:
            continue
        position = haystack.find(f" {source.name_norm} ")
        if position >= 0:
            hits.append((position, source))
    hits.sort(key=lambda hit: hit[0])
    return [source for _, source in hits[:MAX_MENTIONS]]


def excerpt(text: str, limit: int = 160) -> str:
    """Whitespace-collapsed text cut on a word boundary, marked with "..." when cut."""
    flat = _SPACES.sub(" ", text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0] or flat[:limit]
    return f"{cut.rstrip()}..."
