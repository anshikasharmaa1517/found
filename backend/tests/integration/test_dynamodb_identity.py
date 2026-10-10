from datetime import UTC, datetime, timedelta

from found_core.adapters.dynamodb import identity_decision_key, identity_proposal_key
from found_core.domain.models import IdentityDecision, IdentityProposal

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def proposal(key="per_A|per_B", incident="inc_1") -> IdentityProposal:
    a, b = key.split("|")
    return IdentityProposal(
        pair_key=key,
        incident_id=incident,
        person_a_id=a,
        person_b_id=b,
        reasons=("GIVEN_EXACT", "AGE_EQUAL", "SHARED_LOCATION"),
        score=55,
        proposed_by="resolver",
        created_at=AT,
    )


def decision(version=1, verdict="CONFIRMED", history=(), key="per_A|per_B") -> IdentityDecision:
    a, b = key.split("|")
    return IdentityDecision(
        pair_key=key,
        incident_id="inc_1",
        person_a_id=a,
        person_b_id=b,
        decision=verdict,
        reviewer_id=f"rev_{version}",
        note="Same age, same bridge.",
        evidence_claim_ids=("clm_1",),
        version=version,
        decided_at=AT + timedelta(hours=version),
        history=history,
    )


def test_proposal_is_stored_once_under_its_design_key(repo, table):
    assert repo.put_identity_proposal_if_absent(proposal())
    assert not repo.put_identity_proposal_if_absent(proposal())
    item = table.get_item(Key=identity_proposal_key("inc_1", "per_A|per_B"))["Item"]
    assert item["entity_type"] == "IDENTITY_PROPOSAL" and item["SK"] == "IDP#per_A|per_B"
    assert repo.get_identity_proposal("inc_1", "per_A|per_B") == proposal()
    assert repo.get_identity_proposal("inc_2", "per_A|per_B") is None


def test_decision_versions_are_checked_and_history_round_trips(repo, table):
    first = decision()
    assert repo.save_identity_decision(first, 0)
    assert not repo.save_identity_decision(decision(verdict="REJECTED"), 0)
    second = decision(2, "REJECTED", history=(first.record(),))
    assert not repo.save_identity_decision(second, 2)
    assert repo.save_identity_decision(second, 1)
    stored = repo.get_identity_decision("inc_1", "per_A|per_B")
    assert stored == second and stored.history[0].reviewer_id == "rev_1"
    item = table.get_item(Key=identity_decision_key("inc_1", "per_A|per_B"))["Item"]
    assert item["entity_type"] == "IDENTITY_DECISION" and item["version"] == 2


def test_a_persons_decisions_come_from_either_side_of_the_pair(repo):
    repo.save_identity_decision(decision(key="per_A|per_B"), 0)
    repo.save_identity_decision(decision(key="per_B|per_C"), 0)
    repo.save_identity_decision(decision(key="per_C|per_D"), 0)
    assert [d.pair_key for d in repo.list_identity_decisions("inc_1", "per_B")] == [
        "per_A|per_B",
        "per_B|per_C",
    ]
    assert repo.list_identity_decisions("inc_1", "per_Z") == []
    assert repo.list_identity_decisions("inc_2", "per_B") == []


def test_demo_reset_removes_the_incidents_proposals_and_decisions(repo):
    repo.put_identity_proposal_if_absent(proposal())
    repo.put_identity_proposal_if_absent(proposal("per_X|per_Y", incident="inc_2"))
    repo.save_identity_decision(decision(), 0)
    repo.delete_incident_data("inc_1")
    assert repo.get_identity_proposal("inc_1", "per_A|per_B") is None
    assert repo.get_identity_decision("inc_1", "per_A|per_B") is None
    assert repo.get_identity_proposal("inc_2", "per_X|per_Y") is not None
