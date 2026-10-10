"""Climate layers: roads, bridges, shelters, aid points, hazards and places (FR-10, UC-7).

Pure: no I/O. Each subject becomes one map feature with a label that cites the claim it
comes from and lists disagreeing sources, so "Bridge closed" from the police and "Bridge
open" from a volunteer both stay visible. Nothing is overwritten or decided here.

Roads, bridges and shelters have status semantics (design Section 9.1); for the other
types the label is simply the latest report, and says so.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from found_core.domain.enums import STATUS_TYPES, SubjectType
from found_core.domain.models import Claim, Location, Source, Subject
from found_core.domain.rules import PLAIN_STATUS, latest_by_report_time, report_order, summarize

CLIMATE_TYPES = (
    SubjectType.INFRASTRUCTURE,
    SubjectType.SHELTER,
    SubjectType.AID_POINT,
    SubjectType.HAZARD,
    SubjectType.PLACE,
)
RECENT_REPORTS = 5
CAVEAT = (
    "Places and conditions are as reported and unverified. Disagreeing reports are all "
    "shown; none is hidden."
)


@dataclass(frozen=True)
class FeatureReport:
    claim: Claim
    source_name: str


@dataclass(frozen=True)
class ClimateFeature:
    subject: Subject
    label: str
    basis: str
    cited_claim_id: str | None
    location: Location | None
    conflicts: list[FeatureReport] = field(default_factory=list)
    recent: list[FeatureReport] = field(default_factory=list)
    report_count: int = 0
    needs_review: bool = False


def plain(claim_type: str) -> str:
    return PLAIN_STATUS.get(claim_type, claim_type.lower().replace("_", " "))


def build_feature(
    subject: Subject,
    claims: Sequence[Claim],
    locations: Mapping[str, Location],
    sources: Mapping[str, Source],
) -> ClimateFeature:
    def named(claim: Claim) -> FeatureReport:
        source = sources.get(claim.source_id)
        return FeatureReport(claim=claim, source_name=source.name if source else claim.source_id)

    by_id = {c.id: c for c in claims}
    newest_first = sorted(claims, key=report_order, reverse=True)
    label, basis, cited = "No reports", "No reports yet", None
    conflicts: list[FeatureReport] = []
    needs_review = False
    if subject.subject_type in STATUS_TYPES:
        summary = summarize(claims, subject.subject_type)
        label, basis, cited = summary.label, summary.basis, summary.cited_claim_id
        conflicts = [named(by_id[cid]) for cid in summary.conflicts]
        needs_review = summary.needs_review
    elif claims:
        latest = latest_by_report_time(claims)
        label = f"Latest report: {plain(latest.claim_type)}"
        basis = "Latest report; these reports do not form a status"
        cited = latest.id

    # The place is where the newest located report puts it, as reported.
    located = next((c for c in newest_first if c.location_id in locations), None)
    return ClimateFeature(
        subject=subject,
        label=label,
        basis=basis,
        cited_claim_id=cited,
        location=locations[located.location_id] if located and located.location_id else None,
        conflicts=conflicts,
        recent=[named(c) for c in newest_first[:RECENT_REPORTS]],
        report_count=len(claims),
        needs_review=needs_review,
    )
