"""Sending to open WebSocket connections."""

from typing import Protocol


class ConnectionGateway(Protocol):
    def send(self, connection_id: str, data: bytes) -> bool:
        """Deliver one message. False when the connection no longer exists."""
        ...

    def close(self, connection_id: str) -> None:
        """Close a connection. Already closed is not an error."""
        ...
