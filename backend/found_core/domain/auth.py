"""The verified caller of a request, built from token claims checked by API Gateway."""

from dataclasses import dataclass
from typing import Any

from found_core.domain.errors import Unauthenticated

PUBLISHER = "publisher"
REVIEWER = "reviewer"
FAMILY = "family"
ADMIN = "admin"


def _groups(raw: Any) -> frozenset[str]:
    """Cognito groups arrive as a list, or as "[a b]" after HTTP API flattens the claim."""
    if raw is None:
        return frozenset()
    if isinstance(raw, list | tuple):
        return frozenset(str(g) for g in raw)
    text = str(raw).strip().strip("[]")
    return frozenset(g.strip('"') for g in text.replace(",", " ").split() if g)


@dataclass(frozen=True)
class Caller:
    user_id: str
    groups: frozenset[str]
    org_id: str | None = None

    def has(self, group: str) -> bool:
        return group in self.groups

    @classmethod
    def from_claims(cls, claims: dict[str, Any] | None) -> "Caller":
        claims = claims or {}
        user_id = claims.get("sub")
        if not user_id:
            raise Unauthenticated("Sign in required.")
        return cls(
            user_id=str(user_id),
            groups=_groups(claims.get("cognito:groups")),
            org_id=claims.get("custom:org_id") or None,
        )
