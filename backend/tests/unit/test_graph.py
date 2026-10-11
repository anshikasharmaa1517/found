from datetime import UTC, datetime

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.errors import Forbidden, NotFound
from found_core.domain.graph import build_graph
from found_core.domain.models import (
    Claim,
    IdentityDecision,
    IdentityProposal,
    Investigation,
    Location,
    Source,
    Subject,
)
from found_core.services.graph import GraphService
from found_core.services.ingest import IngestService
from found_core.services.resolve import ResolveService
from tests.unit.test_api_handler import call, event

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)
REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
FAMILY = Caller(user_id="fam_1", groups=frozenset({"family"}))


def subject(sid, name, kind="PERSON"):
    return Subject(
        id=sid, incident_id="inc_1", subject_type=kind, display_name=name, name_norm=name.lower()
    )


def source(sid, name):
    return Source(id=sid, incident_id="inc_1", name=name, name_norm=name.lower(), source_type="NGO")


def claim(cid, sid, src, claim_type="MISSING", loc=None, mentions=()):
    return Claim(
        id=cid,
        incident_id="inc_1",
        subject_id=sid,
        subject_type="PERSON",
        source_id=src,
        seq=1,
        claim_type=claim_type,
        original_text="text",
        external_reference=cid,
        ingested_at=AT,
        extraction_method="structured_form",
        payload_hash=cid,
        mentioned_source_ids=mentions,
        location_id=loc,
        created_by="pub",
    )


SUBJECTS = [
    subject("per_a", "Sita Tamang"),
    subject("per_b", "Sita T."),
    subject("inf_1", "Old Bridge", "INFRASTRUCTURE"),
]
SOURCES = [
    source("src_h", "Central Hospital Demo"),
    source("src_n", "Flood Relief Demo"),
    source("src_x", "Unused Desk"),
]
PLACES = [Location(id="loc_1", incident_id="inc_1", name="Old Bridge", name_norm="old bridge")]
CLAIMS = [
    claim("clm_1", "per_a", "src_h", "FOUND_SAFE", loc="loc_1"),
    claim("clm_2", "per_a", "src_n", "FOUND_SAFE", mentions=("src_h",)),
    claim("clm_3", "per_a", "src_h", "DECEASED", loc="loc_1"),
]
INVESTIGATION = Investigation(
    id="inv_1",
    incident_id="inc_1",
    claim_id="clm_2",
    fingerprint="fp",
    mode="LIVE",
    status="NEEDS_REVIEW",
    model_id="m",
    prompt_version="p",
    agent_version="a",
    attribution="RELAY",
    comparison="SUPPORTS",
    referenced_source_id="src_h",
    created_by="rev_1",
    queued_at=AT,
)
PROPOSAL = IdentityProposal(
    pair_key="per_a|per_b",
    incident_id="inc_1",
    person_a_id="per_a",
    person_b_id="per_b",
    reasons=("GIVEN_EXACT",),
    score=55,
    proposed_by="resolver",
    created_at=AT,
)


def kinds(graph):
    return {(e.source, e.target, e.kind) for e in graph.edges}


def test_every_edge_comes_from_a_stored_field():
    graph = build_graph(
        subjects=SUBJECTS,
        claims=CLAIMS,
        sources=SOURCES,
        locations=PLACES,
        investigations=[INVESTIGATION],
        proposals=[PROPOSAL],
        reviewer=True,
    )
    assert kinds(graph) >= {
        ("clm_1", "per_a", "about"),
        ("clm_1", "src_h", "from"),
        ("clm_1", "loc_1", "at"),
        ("clm_2", "src_h", "mentions"),
        ("inv_1", "clm_2", "traced"),
        ("inv_1", "src_h", "relays"),
        ("per_a", "per_b", "possibly_same"),
    }
    nodes = {n.id: n for n in graph.nodes}
    assert nodes["clm_3"].label == "Deceased" and nodes["inv_1"].detail == "relay, supports"
    assert nodes["inf_1"].kind == "subject" and nodes["per_a"].kind == "person"
    # A source no report points to is left out.
    assert "src_x" not in nodes
    assert graph.by_kind["report"] == 3


def test_non_reviewers_get_no_reviewer_work_and_no_sensitive_details():
    graph = build_graph(
        subjects=SUBJECTS,
        claims=CLAIMS,
        sources=SOURCES,
        locations=PLACES,
        investigations=[INVESTIGATION],
        proposals=[PROPOSAL],
        withheld={"clm_3"},
        reviewer=False,
    )
    nodes = {n.id: n for n in graph.nodes}
    assert "inv_1" not in nodes
    assert nodes["clm_3"].label == "Sensitive report" and nodes["clm_3"].detail is None
    edges = kinds(graph)
    assert ("clm_3", "per_a", "about") in edges
    assert not any(e[0] == "clm_3" and e[2] != "about" for e in edges)
    assert not any(e[2] == "possibly_same" for e in edges)


def test_a_decision_replaces_the_proposal_and_everyone_sees_it():
    decision = IdentityDecision(
        pair_key="per_a|per_b",
        incident_id="inc_1",
        person_a_id="per_a",
        person_b_id="per_b",
        decision="CONFIRMED",
        reviewer_id="rev_1",
        note="Same bridge.",
        version=1,
        decided_at=AT,
    )
    for reviewer in (True, False):
        graph = build_graph(
            subjects=SUBJECTS,
            claims=CLAIMS,
            sources=SOURCES,
            locations=PLACES,
            proposals=[PROPOSAL],
            decisions=[decision],
            reviewer=reviewer,
        )
        pair = [e for e in graph.edges if e.source == "per_a" and e.target == "per_b"]
        assert [e.kind for e in pair] == ["same_person"]


def test_the_demo_incident_graph_links_sita_her_sources_and_the_proposed_match():
    from found_core.fixtures import load_dataset
    from tests.unit.test_dataset import read_dataset

    repo = InMemoryFoundRepository()
    loaded = load_dataset(read_dataset(), repo, IngestService(repo, sleep=lambda _: None))
    resolver = ResolveService(repo)
    for person_id in loaded.subjects_by_person.values():
        resolver.on_person_created(person_id)
    graph = GraphService(repo).graph(REVIEWER, "inc_demo")
    by_label = {(n.kind, n.label): n for n in graph.nodes}
    sita = by_label[("person", "Sita Tamang")]
    other = by_label[("person", "Sita T.")]
    assert any(
        {e.source, e.target} == {sita.id, other.id} and e.kind == "possibly_same"
        for e in graph.edges
    )
    assert any(e.kind == "mentions" for e in graph.edges)
    assert graph.by_kind["subject"] >= 6

    with pytest.raises(NotFound):
        GraphService(repo).graph(REVIEWER, "inc_9")
    outsider = Caller(user_id="p", groups=frozenset({"publisher"}), org_id="org_x")
    with pytest.raises(Forbidden):
        GraphService(repo).graph(outsider, "inc_demo")
    family = GraphService(repo).graph(FAMILY, "inc_demo")
    assert "investigation" not in family.by_kind
    assert any(n.label == "Sensitive report" for n in family.nodes)


def test_the_graph_route(monkeypatch):
    repo = InMemoryFoundRepository()
    repo.add_incident("inc_1")
    monkeypatch.setattr(container, "graph_service", lambda: GraphService(repo))
    family = {"sub": "f", "cognito:groups": "[family]"}
    status, body, _ = call(event("GET", "/v1/incidents/inc_1/graph", claims=family))
    assert status == 200 and body == {"nodes": [], "edges": [], "by_kind": {}}
