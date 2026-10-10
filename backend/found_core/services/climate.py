"""The climate picture for an incident: one sourced feature per non-person subject.

Design UC-7 and FR-10. Like the place counts, the layer reads the whole incident, so
each Lambda environment keeps it for 30 seconds and says how fresh it is. Access is
checked on every call.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from found_core.domain.auth import Caller
from found_core.domain.climate import CLIMATE_TYPES, ClimateFeature, build_feature
from found_core.domain.errors import NotFound
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import FoundRepository
from found_core.services.access import ensure_can_read

CACHE_SECONDS = 30
# Enough for a district; the layer is a picture, not an inventory.
MAX_PER_TYPE = 200


@dataclass(frozen=True)
class ClimateLayer:
    features: list[ClimateFeature]
    updated_at: datetime


class ClimateService:
    def __init__(
        self,
        repo: FoundRepository,
        clock: Clock | None = None,
        cache_seconds: int = CACHE_SECONDS,
    ) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()
        self._ttl = timedelta(seconds=cache_seconds)
        self._cache: dict[str, ClimateLayer] = {}

    def layer(self, caller: Caller, incident_id: str) -> ClimateLayer:
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        ensure_can_read(self._repo, caller, incident_id)

        now = self._clock.now()
        cached = self._cache.get(incident_id)
        if cached is not None and now - cached.updated_at < self._ttl:
            return cached
        locations = {loc.id: loc for loc in self._repo.list_locations(incident_id)}
        sources = {s.id: s for s in self._repo.list_sources(incident_id)}
        features = [
            build_feature(subject, self._repo.list_subject_claims(subject.id), locations, sources)
            for subject_type in CLIMATE_TYPES
            for subject in self._repo.list_subjects(incident_id, subject_type, MAX_PER_TYPE)
        ]
        fresh = ClimateLayer(features=features, updated_at=now)
        self._cache[incident_id] = fresh
        return fresh
