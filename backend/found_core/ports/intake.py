"""Ports the intake workflow needs: object storage, text reading and candidate extraction."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StoredObject:
    content_type: str
    size: int
    data: bytes


class ExtractionFailed(Exception):
    """The model or text reader gave nothing usable. The job is marked FAILED with this."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ObjectStore(Protocol):
    def presign_post(
        self, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> dict[str, Any]:
        """A browser upload form bound to one key, one content type and a size limit."""
        ...

    def put_text(self, key: str, text: str) -> None: ...

    def read(self, key: str, max_bytes: int) -> StoredObject:
        """The object's bytes. Raises ValueError if it is larger than `max_bytes`."""
        ...


class TextReader(Protocol):
    def read_text(self, key: str) -> str:
        """Text lines found in an image or single-page PDF, joined by newlines."""
        ...


class CandidateExtractor(Protocol):
    def extract(self, text: str) -> list[Any]:
        """Raw candidates from the model's forced `emit_candidates` call."""
        ...
