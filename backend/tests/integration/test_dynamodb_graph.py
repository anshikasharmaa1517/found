from datetime import UTC, datetime, timedelta

from found_core.domain.models import Investigation
from tests.integration.test_dynamodb_identity import decision, proposal

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def investigation(inv_id, incident="inc_1", minutes=0):
    return Investigation(
        id=inv_id,
        incident_id=incident,
        claim_id="clm_1",
        fingerprint=f"fp_{inv_id}",
        mode="LIVE",
        status="QUEUED",
        model_id="m",
        prompt_version="p",
        agent_version="a",
        created_by="rev_1",
        queued_at=AT + timedelta(minutes=minutes),
    )


def test_an_incidents_investigations_are_listed_and_only_its_own(repo):
    repo.put_investigation(investigation("inv_2", minutes=2))
    repo.put_investigation(investigation("inv_1"))
    repo.put_investigation(investigation("inv_x", incident="inc_2"))
    assert [i.id for i in repo.list_incident_investigations("inc_1")] == ["inv_1", "inv_2"]


def test_an_incidents_identity_records_are_listed(repo):
    repo.put_identity_proposal_if_absent(proposal())
    repo.save_identity_decision(decision(), 0)
    repo.put_identity_proposal_if_absent(proposal("per_X|per_Y", incident="inc_2"))
    proposals, decisions = repo.list_incident_identity("inc_1")
    assert [p.pair_key for p in proposals] == ["per_A|per_B"]
    assert [d.pair_key for d in decisions] == ["per_A|per_B"]
