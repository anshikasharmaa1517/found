from typing import Protocol


class InvestigationQueue(Protocol):
    def send(self, investigation_id: str) -> None:
        """Hand a queued investigation to the runner. The message carries only the id."""
        ...
