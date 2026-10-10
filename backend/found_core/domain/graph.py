"""The incident as a graph of stored records and the typed links between them.

Pure: no I/O. Every node is a stored record with its real id, and every edge comes from a
stored field (a claim's subject, source, place and mentioned sources; an investigation's
claim and referenced source; an identity proposal or decision). Nothing is inferred here.

Sensitive reports a caller may not see are nodes without their type, text or source
(product rule 8). Investigations and proposals are reviewer work and only reach reviewers.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from found_core.domain.enums import IdentityVerdict, SubjectType
from found_core.domain.models import (
    Claim,
    IdentityDecision,
    IdentityProposal,
    Investigation,
    Location,
    Source,
    Subject,
)
from found_core.domain.rules import PLAIN_STATUS


@dataclass(frozen=True)
class Node:
    id: str
    kind: str  # person, subject, report, source, place, investigation
    label: str
    detail: str | None = None
    subject_type: str | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str  # about, from, at, mentions, traced, relays, possibly_same, same_person, not_same


@dataclass(frozen=True)
class Graph:
    nodes: list[Node]
    edges: list[Edge]
    by_kind: dict[str, int] = field(default_factory=dict)


def _plain(claim_type: str) -> str:
    return PLAIN_STATUS.get(claim_type, claim_type.lower().replace("_", " "))


def build_graph(
    *,
    subjects: Iterable[Subject],
    claims: Iterable[Claim],
    sources: Iterable[Source],
    locations: Iterable[Location],
    investigations: Iterable[Investigation] = (),
    proposals: Iterable[IdentityProposal] = (),
    decisions: Iterable[IdentityDecision] = (),
    withheld: Collection[str] = frozenset(),
    reviewer: bool = False,
) -> Graph:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    source_names = {s.id: s.name for s in sources}

    for s in subjects:
        person = s.subject_type == SubjectType.PERSON
        nodes[s.id] = Node(
            id=s.id,
            kind="person" if person else "subject",
            label=s.display_name,
            detail=(f"Age {s.age}" if s.age is not None else None) if person else None,
            subject_type=s.subject_type.value,
        )
    for source_id, name in source_names.items():
        nodes[source_id] = Node(id=source_id, kind="source", label=name)
    for loc in locations:
        nodes[loc.id] = Node(id=loc.id, kind="place", label=loc.name)

    for c in claims:
        if c.subject_id not in nodes:
            continue
        hidden = c.id in withheld
        nodes[c.id] = Node(
            id=c.id,
            kind="report",
            label="Sensitive report" if hidden else _plain(c.claim_type).capitalize(),
            detail=None if hidden else source_names.get(c.source_id),
        )
        edges.append(Edge(c.id, c.subject_id, "about"))
        if hidden:
            continue  # No source, place or mentions for a report this caller may not see.
        if c.source_id in nodes:
            edges.append(Edge(c.id, c.source_id, "from"))
        if c.location_id and c.location_id in nodes:
            edges.append(Edge(c.id, c.location_id, "at"))
        for mentioned in c.mentioned_source_ids:
            if mentioned in nodes:
                edges.append(Edge(c.id, mentioned, "mentions"))

    if reviewer:
        for inv in investigations:
            if inv.claim_id not in nodes:
                continue
            finding = (
                f"{inv.attribution.value.lower()}, {inv.comparison.value.lower().replace('_', ' ')}"
                if inv.attribution and inv.comparison
                else inv.status.value.lower().replace("_", " ")
            )
            nodes[inv.id] = Node(
                id=inv.id, kind="investigation", label="Investigation", detail=finding
            )
            edges.append(Edge(inv.id, inv.claim_id, "traced"))
            if inv.referenced_source_id and inv.referenced_source_id in nodes:
                edges.append(Edge(inv.id, inv.referenced_source_id, "relays"))

    decided = {d.pair_key: d for d in decisions}
    pairs: dict[str, tuple[str, str, str]] = {}
    if reviewer:
        for p in proposals:
            pairs[p.pair_key] = (p.person_a_id, p.person_b_id, "possibly_same")
    for key, d in decided.items():
        kind = "same_person" if d.decision == IdentityVerdict.CONFIRMED else "not_same"
        pairs[key] = (d.person_a_id, d.person_b_id, kind)
    for a, b, kind in pairs.values():
        if a in nodes and b in nodes:
            edges.append(Edge(a, b, kind))

    # Sources and places no report points to add nothing to the picture.
    linked = {e.source for e in edges} | {e.target for e in edges}
    kept = [n for n in nodes.values() if n.kind not in ("source", "place") or n.id in linked]
    by_kind: dict[str, int] = {}
    for n in kept:
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
    return Graph(nodes=kept, edges=edges, by_kind=by_kind)
