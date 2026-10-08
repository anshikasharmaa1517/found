"""Who may see sensitive reports, and what everyone else sees instead (product rule 8).

A `DECEASED` report is shown in full only to reviewers and admins until a reviewer
releases it, so a family hears it from a coordinator first. Everyone else gets a neutral
notice in its place: the API leaves out the type, the text and the source, not only the
web app. The summary still cites the claim it is based on (product rule 1).
"""

from collections.abc import Collection, Iterable
from dataclasses import replace

from found_core.domain.auth import ADMIN, REVIEWER, Caller
from found_core.domain.enums import SENSITIVE_CLAIM_TYPES
from found_core.domain.models import Claim
from found_core.domain.rules import CitedSummary

SENSITIVE_NOTICE = "A sensitive report was received. A coordinator will contact you."
SENSITIVE_LABEL = "Sensitive report received"
SENSITIVE_BASIS = "A coordinator will contact you before the details are shown"


def sees_sensitive(caller: Caller) -> bool:
    return caller.has(REVIEWER) or caller.has(ADMIN)


def is_sensitive(claim: Claim) -> bool:
    return claim.claim_type in SENSITIVE_CLAIM_TYPES


def withheld_ids(
    claims: Iterable[Claim], caller: Caller, released: Collection[str]
) -> frozenset[str]:
    """Claims this caller may not see in full. Unreleased means withheld, never the reverse."""
    if sees_sensitive(caller):
        return frozenset()
    return frozenset(c.id for c in claims if is_sensitive(c) and c.id not in released)


def masked_summary(summary: CitedSummary, withheld: Collection[str]) -> CitedSummary:
    if summary.cited_claim_id not in withheld:
        return summary
    return replace(summary, label=SENSITIVE_LABEL, basis=SENSITIVE_BASIS)
