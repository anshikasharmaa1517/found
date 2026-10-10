"""Possible same-person pairs and their explained score (design Sections 6.3 and 9.7).

Pure: no I/O. The resolver only proposes; a reviewer decides. Names alone never produce
a proposal: a pair also needs a close age or a shared place (product rule 6).
"""

from dataclasses import dataclass

from found_core.domain.errors import BadRequest
from found_core.domain.models import Subject

PROPOSE_AT = 50
CANDIDATE_CAP = 50
_NON_NAME_PREFIXES = ("AGE_", "SHARED_")


def pair_key(a: str, b: str) -> str:
    """The pair's id: both person ids, sorted, joined by `|`."""
    if a == b:
        raise ValueError("a pair needs two different people")
    first, second = sorted((a, b))
    return f"{first}|{second}"


def parse_pair_key(raw: str) -> tuple[str, str]:
    """The two person ids of a pair key. Refuses keys that are not sorted and distinct."""
    parts = raw.split("|")
    if len(parts) != 2 or not all(p.startswith("per_") for p in parts):
        raise BadRequest("pair_key must be two person ids joined by |.")
    if parts[0] >= parts[1]:
        raise BadRequest("pair_key must name two different people in sorted order.")
    return parts[0], parts[1]


@dataclass(frozen=True)
class NameParts:
    """Given name and surname from the normalized name. One-word names have no surname."""

    full: str
    given: str
    surname: str

    @classmethod
    def of(cls, name_norm: str) -> "NameParts":
        words = name_norm.split()
        if not words:
            return cls(full="", given="", surname="")
        return cls(full=name_norm, given=words[0], surname=words[-1] if len(words) > 1 else "")


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance: insertions, deletions and substitutions."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class ScoredPair:
    person_a_id: str
    person_b_id: str
    score: int
    reasons: tuple[str, ...]
    propose: bool

    @property
    def pair_key(self) -> str:
        return pair_key(self.person_a_id, self.person_b_id)


def score(a: Subject, b: Subject, *, shared_location: bool) -> ScoredPair:
    """Points and reasons for one pair, in the order of design Section 9.7."""
    reasons: list[str] = []
    points = 0
    na, nb = NameParts.of(a.name_norm), NameParts.of(b.name_norm)
    if na.full and na.full == nb.full:
        reasons.append("FULL_NAME_EXACT")
        points += 50
    else:
        if na.surname and na.surname == nb.surname:
            reasons.append("SURNAME_EXACT")
            points += 25
        if na.given and na.given == nb.given:
            reasons.append("GIVEN_EXACT")
            points += 20
        elif na.given and na.given[:1] == nb.given[:1]:
            reasons.append("GIVEN_INITIAL")
            points += 10
        if edit_distance(na.full, nb.full) == 1:
            reasons.append("NAME_EDIT_DISTANCE_1")
            points += 15
    if a.age is not None and b.age is not None:
        diff = abs(a.age - b.age)
        if diff == 0:
            reasons.append("AGE_EQUAL")
            points += 20
        elif diff <= 2:
            reasons.append("AGE_WITHIN_2")
            points += 10
        elif diff > 5:
            reasons.append("AGE_DIFF_GT_5")
            points -= 30
    if shared_location:
        reasons.append("SHARED_LOCATION")
        points += 15
    has_non_name = any(r.startswith(_NON_NAME_PREFIXES) and r != "AGE_DIFF_GT_5" for r in reasons)
    first, second = sorted((a.id, b.id))
    return ScoredPair(
        person_a_id=first,
        person_b_id=second,
        score=points,
        reasons=tuple(reasons),
        propose=points >= PROPOSE_AT and has_non_name,
    )
