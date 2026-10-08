"""WebSocket connections and live push (design Sections 5.4, 6.5, 7.5 and 10.2)."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from found_core.domain.auth import Caller
from found_core.domain.errors import BadRequest, NotFound
from found_core.domain.models import Connection
from found_core.events import AlertCreated, DomainEvent
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.connections import ConnectionGateway
from found_core.ports.repository import FoundRepository
from found_core.realtime import (
    CONNECTION_HOURS,
    MAX_CONNECTIONS_PER_USER,
    message_for,
    receives,
)
from found_core.services.access import ensure_can_read

MAX_ID_LENGTH = 64
PUSH_WORKERS = 16


def _caller_of(connection: Connection) -> Caller:
    return Caller(
        user_id=connection.user_id, groups=frozenset(connection.groups), org_id=connection.org_id
    )


class ConnectionService:
    def __init__(
        self, repo: FoundRepository, gateway: ConnectionGateway, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._clock = clock or SystemClock()

    def connect(self, caller: Caller, connection_id: str) -> Connection:
        now = self._clock.now()
        connection = Connection(
            id=connection_id,
            user_id=caller.user_id,
            groups=tuple(sorted(caller.groups)),
            org_id=caller.org_id,
            connected_at=now,
            expires_at=now + timedelta(hours=CONNECTION_HOURS),
        )
        self._repo.put_connection(connection)
        # Over the cap, the oldest connections go, so a tab that closed without saying
        # goodbye can never lock its user out.
        others = sorted(
            (
                c
                for c in self._repo.list_user_connections(caller.user_id)
                if c.id != connection_id and c.expires_at > now
            ),
            key=lambda c: (c.connected_at, c.id),
        )
        excess = len(others) + 1 - MAX_CONNECTIONS_PER_USER
        for old in others[: max(excess, 0)]:
            self._repo.delete_connection(old.id)
            self._gateway.close(old.id)
        return connection

    def disconnect(self, connection_id: str) -> None:
        self._repo.delete_connection(connection_id)

    def subscribe(self, connection_id: str, body: dict[str, Any]) -> str:
        connection = self._repo.get_connection(connection_id)
        if connection is None:
            raise NotFound("Connection not found.")
        incident_id = body.get("incident_id")
        if not isinstance(incident_id, str) or not 0 < len(incident_id) <= MAX_ID_LENGTH:
            raise BadRequest("incident_id is required.")
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, _caller_of(connection), incident_id)
        if not self._repo.set_connection_incident(connection_id, incident_id):
            raise NotFound("Connection not found.")
        return incident_id


@dataclass(frozen=True)
class PushResult:
    sent: int = 0
    gone: int = 0
    failed: int = 0


class PushService:
    def __init__(
        self, repo: FoundRepository, gateway: ConnectionGateway, clock: Clock | None = None
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._clock = clock or SystemClock()

    def push(self, event: DomainEvent) -> PushResult:
        message = message_for(event)
        if message is None:
            return PushResult()
        if isinstance(event, AlertCreated):
            candidates = self._repo.list_user_connections(event.user_id)
        else:
            candidates = self._repo.list_incident_connections(event.incident_id)
        now = self._clock.now()
        targets = [c for c in candidates if c.expires_at > now and receives(c, event)]
        if not targets:
            return PushResult()

        data = json.dumps(message, ensure_ascii=False).encode()

        def send(connection: Connection) -> str:
            # One broken connection must not stop the others or trigger a retry that
            # would repeat the message to everyone.
            try:
                return "sent" if self._gateway.send(connection.id, data) else "gone"
            except Exception:
                return "failed"

        with ThreadPoolExecutor(max_workers=min(PUSH_WORKERS, len(targets))) as pool:
            outcomes = list(pool.map(send, targets))
        for connection, outcome in zip(targets, outcomes, strict=True):
            if outcome == "gone":
                self._repo.delete_connection(connection.id)
        return PushResult(
            sent=outcomes.count("sent"),
            gone=outcomes.count("gone"),
            failed=outcomes.count("failed"),
        )
