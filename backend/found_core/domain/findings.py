"""Finding validation and outcome rules (design Section 9.8). Pure: no I/O.

The model proposes labels and citations. Code checks every one against stored claims
and then decides the outcome. A relay is never treated as independent confirmation:
every relay goes to a reviewer, even one that agrees with its source.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from found_core.domain.enums import Attribution, Comparison, InvestigationStatus
from found_core.domain.models import Citation, Claim

EXCERPT_MIN = 10
EXCERPT_MAX = 300
SUMMARY_MAX = 600
MAX_CITATIONS = 8

_SPACES = re.compile(r"\s+")


class FindingInput(BaseModel):
    """What `record_finding` accepts. Unknown fields are refused, not ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attribution: Attribution
    referenced_source_id: str | None = None
    comparison: Comparison
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX)
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=MAX_CITATIONS)


@dataclass(frozen=True)
class FindingError:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class Outcome:
    status: InvestigationStatus
    reasons: tuple[str, ...]
    priority: int | None = None


def _flat(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def quotes(excerpt: str, text: str) -> bool:
    """True if the excerpt appears verbatim in the text, ignoring whitespace runs."""
    return _flat(excerpt) in _flat(text)


def validate_finding(
    finding: FindingInput,
    claim: Claim,
    cited: Mapping[str, Claim],
    source_has_reports: bool,
) -> list[FindingError]:
    """Every reason to refuse the finding. Empty means it may be stored.

    `cited` holds the cited claims that exist in the investigation's incident.
    `source_has_reports` tells whether the referenced source has any claim.
    """
    errors: list[FindingError] = []
    source_id = finding.referenced_source_id
    if source_id is not None and source_id not in claim.mentioned_source_ids:
        errors.append(
            FindingError(
                "SOURCE_NOT_IN_MENU",
                "referenced_source_id must be one of the sources the report mentions.",
                "referenced_source_id",
            )
        )

    for n, citation in enumerate(finding.citations):
        field = f"citations[{n}]"
        target = cited.get(citation.claim_id)
        if target is None:
            errors.append(
                FindingError("UNKNOWN_CLAIM", "Cited claim is not in this incident.", field)
            )
            continue
        length = len(_flat(citation.excerpt))
        if not EXCERPT_MIN <= length <= EXCERPT_MAX:
            errors.append(
                FindingError(
                    "EXCERPT_LENGTH",
                    f"Excerpt must be {EXCERPT_MIN} to {EXCERPT_MAX} characters.",
                    field,
                )
            )
        elif not quotes(citation.excerpt, target.original_text):
            errors.append(
                FindingError(
                    "EXCERPT_NOT_FOUND", "Excerpt must quote the cited claim exactly.", field
                )
            )

    if all(c.claim_id != claim.id for c in finding.citations):
        errors.append(
            FindingError("CLAIM_NOT_CITED", "The investigated claim must be cited.", "citations")
        )

    comparable = source_id is not None and source_has_reports
    if not comparable and finding.comparison != Comparison.NOT_APPLICABLE:
        errors.append(
            FindingError(
                "NOTHING_TO_COMPARE",
                "comparison must be NOT_APPLICABLE when no source with reports is referenced.",
                "comparison",
            )
        )
    if comparable and finding.attribution == Attribution.RELAY:
        if finding.comparison == Comparison.NOT_APPLICABLE:
            errors.append(
                FindingError(
                    "COMPARISON_REQUIRED",
                    "A relay of a source with reports must be compared with them.",
                    "comparison",
                )
            )
        if not any(
            c.claim_id in cited and cited[c.claim_id].source_id == source_id
            for c in finding.citations
        ):
            errors.append(
                FindingError(
                    "SOURCE_NOT_CITED",
                    "Cite at least one report from the referenced source.",
                    "citations",
                )
            )
    return errors


# Review priority per reason code, 1 first. A finding's priority is its most urgent reason,
# so it can be rebuilt from the stored reasons alone.
REASON_PRIORITY: dict[str, int] = {
    "RELAY_DIFFERS_FROM_SOURCE": 1,
    "COMPARISON_UNCLEAR": 2,
    "SOURCE_NOT_FOUND": 2,
    "ATTRIBUTION_UNCLEAR": 2,
    "DIRECT_BUT_NAMES_SOURCE": 2,
    "RELAY_NOT_FIRST_HAND": 3,
}


def review_priority(reasons: Collection[str]) -> int | None:
    return min((REASON_PRIORITY[r] for r in reasons), default=None)


def _review(*reasons: str) -> Outcome:
    return Outcome(InvestigationStatus.NEEDS_REVIEW, reasons, review_priority(reasons))


def decide_outcome(finding: FindingInput, source_has_reports: bool) -> Outcome:
    """The outcome table of design Section 9.8, for a finding that passed validation."""
    if finding.attribution == Attribution.UNCLEAR:
        return _review("ATTRIBUTION_UNCLEAR")
    if finding.attribution == Attribution.DIRECT:
        if finding.referenced_source_id is None:
            return Outcome(InvestigationStatus.COMPLETED, ())
        return _review("DIRECT_BUT_NAMES_SOURCE")
    if finding.referenced_source_id is None or not source_has_reports:
        return _review("SOURCE_NOT_FOUND")
    match finding.comparison:
        case Comparison.DIFFERS:
            return _review("RELAY_DIFFERS_FROM_SOURCE")
        case Comparison.SUPPORTS:
            return _review("RELAY_NOT_FIRST_HAND")
        case _:
            return _review("COMPARISON_UNCLEAR")


def cited_ids(finding: FindingInput) -> Collection[str]:
    return list(dict.fromkeys(c.claim_id for c in finding.citations))
