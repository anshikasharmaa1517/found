from typing import Any, Protocol


class FixtureSource(Protocol):
    def read(self) -> dict[str, Any]:
        """The dataset files (`incident.json`, ...) parsed from JSON, by file name."""
        ...


class ResetTrigger(Protocol):
    def start(self, incident_id: str, actor: str) -> None:
        """Start a reset in the background worker."""
        ...
