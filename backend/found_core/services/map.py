"""Map place counts with a short in-memory cache (design Sections 7.3 and 11).

Counts read every claim in the incident, so each Lambda environment keeps the result for
30 seconds and the page says how fresh it is. Access is checked on every call; only the
counts are shared between callers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from found_core.domain.auth import Caller
from found_core.domain.errors import NotFound
from found_core.domain.places import PlaceCounts, place_counts
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read

CACHE_SECONDS = 30


@dataclass(frozen=True)
class IncidentMap:
    counts: PlaceCounts
    updated_at: datetime


class MapService:
    def __init__(
        self,
        repo: FoundRepository,
        clock: Clock | None = None,
        cache_seconds: int = CACHE_SECONDS,
    ) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()
        self._ttl = timedelta(seconds=cache_seconds)
        self._cache: dict[str, IncidentMap] = {}

    def incident_map(self, caller: Caller, incident_id: str) -> IncidentMap:
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)

        now = self._clock.now()
        cached = self._cache.get(incident_id)
        if cached is not None and now - cached.updated_at < self._ttl:
            return cached
        counts = place_counts(
            self._repo.list_incident_claims(incident_id),
            self._repo.list_locations(incident_id),
        )
        fresh = IncidentMap(counts=counts, updated_at=now)
        self._cache[incident_id] = fresh
        return fresh
