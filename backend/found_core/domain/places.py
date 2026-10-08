"""Report counts per reported place, for the map (design Sections 2.1 FR-31 and 7.3).

Counts are reports, not people: one person reported three times counts three times.
Places are as reported and unverified. Nothing here says where anyone actually is.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from found_core.domain.enums import Relation
from found_core.domain.models import Claim, Location
from found_core.domain.rules import relations

CAVEAT = "Locations are as reported and unverified. Counts are reports, not unique people."

# The design's buckets. Sensitive and rarer types fall under OTHER on a public map.
BUCKETS = ("MISSING", "FOUND_SAFE", "NEEDS_REVIEW", "OTHER")


@dataclass(frozen=True)
class PlaceCount:
    location: Location
    reports: int
    by_status: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaceCounts:
    places: list[PlaceCount]
    located_reports: int
    unlocated_reports: int
    caveat: str = CAVEAT


def bucket(claim: Claim, relation: Relation) -> str:
    if relation == Relation.NEEDS_REVIEW:
        return "NEEDS_REVIEW"
    if claim.claim_type in ("MISSING", "FOUND_SAFE"):
        return claim.claim_type
    return "OTHER"


def _relations_by_subject(claims: Sequence[Claim]) -> dict[str, Relation]:
    by_subject: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        by_subject[claim.subject_id].append(claim)
    found: dict[str, Relation] = {}
    for subject_claims in by_subject.values():
        found.update(relations(subject_claims))
    return found


def place_counts(claims: Sequence[Claim], locations: Iterable[Location]) -> PlaceCounts:
    plotted = {loc.id: loc for loc in locations if loc.lat is not None and loc.lon is not None}
    relation_of = _relations_by_subject(claims)
    counts: dict[str, dict[str, int]] = {}
    unlocated = 0
    for claim in claims:
        location = plotted.get(claim.location_id or "")
        if location is None:
            unlocated += 1
            continue
        tally = counts.setdefault(location.id, dict.fromkeys(BUCKETS, 0))
        tally[bucket(claim, relation_of[claim.id])] += 1

    places = [
        PlaceCount(location=plotted[loc_id], reports=sum(tally.values()), by_status=tally)
        for loc_id, tally in counts.items()
    ]
    places.sort(key=lambda p: (-p.reports, p.location.name_norm, p.location.id))
    return PlaceCounts(
        places=places,
        located_reports=sum(p.reports for p in places),
        unlocated_reports=unlocated,
    )
