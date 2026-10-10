from datetime import UTC, datetime

import pytest

from found_core.adapters.dynamodb import intake_candidate_key, intake_job_key
from found_core.domain.enums import CandidateStatus, IntakeStatus
from found_core.domain.models import IntakeCandidate, IntakeJob

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def job(job_id="ijb_1", incident="inc_1") -> IntakeJob:
    return IntakeJob(
        id=job_id,
        incident_id=incident,
        organization_id="org_s",
        s3_key=f"intake/{incident}/{job_id}/pasted.txt",
        filename="pasted.txt",
        content_type="text/plain",
        created_by="pub_1",
        created_at=AT,
    )


def candidate(idx=0, job_id="ijb_1") -> IntakeCandidate:
    return IntakeCandidate(
        id=f"icd_{job_id}_{idx}",
        job_id=job_id,
        incident_id="inc_1",
        idx=idx,
        subject_type="PERSON",
        subject_name="Kavita Bisht",
        age=29,
        claim_type="SHELTERED",
        span_text="Kavita Bisht, 29, staying in hall B.",
    )


def test_job_is_stored_under_its_design_keys_and_found_by_id(repo, table):
    repo.put_intake_job(job())
    item = table.get_item(Key=intake_job_key("inc_1", "ijb_1"))["Item"]
    assert item["entity_type"] == "INTAKE_JOB" and item["GSI3PK"] == "IJOB#ijb_1"
    assert repo.get_intake_job("ijb_1") == job()
    assert repo.get_intake_job("ijb_9") is None
    with pytest.raises(ValueError):
        repo.put_intake_job(job())


def test_job_moves_only_from_the_expected_status(repo):
    repo.put_intake_job(job())
    moved = repo.update_intake_job_if(
        "ijb_1", (IntakeStatus.RECEIVED,), {"status": IntakeStatus.EXTRACTING, "sha256": "ab"}
    )
    assert moved.status == IntakeStatus.EXTRACTING and moved.sha256 == "ab"
    assert (
        repo.update_intake_job_if("ijb_1", (IntakeStatus.RECEIVED,), {"status": "FAILED"}) is None
    )
    assert repo.get_intake_job("ijb_1").status == IntakeStatus.EXTRACTING


def test_candidates_are_stored_once_per_index_and_decided_once(repo, table):
    repo.put_intake_candidates([candidate(0), candidate(1)])
    repo.put_intake_candidates([candidate(0).model_copy(update={"subject_name": "Other"})])
    item = table.get_item(Key=intake_candidate_key("ijb_1", 0))["Item"]
    assert item["SK"] == "CAND#000" and item["subject_name"] == "Kavita Bisht"
    assert [c.idx for c in repo.list_intake_candidates("ijb_1")] == [0, 1]
    assert repo.get_intake_candidate("icd_ijb_1_1") == candidate(1)

    confirmed = candidate(0).model_copy(
        update={"status": CandidateStatus.CONFIRMED, "claim_id": "clm_1", "decided_at": AT}
    )
    assert repo.save_candidate_decision(confirmed)
    assert not repo.save_candidate_decision(confirmed.model_copy(update={"claim_id": "clm_2"}))
    assert repo.get_intake_candidate("icd_ijb_1_0").claim_id == "clm_1"


def test_demo_reset_removes_jobs_and_candidates(repo):
    repo.put_intake_job(job())
    repo.put_intake_candidates([candidate(0)])
    repo.put_intake_job(job("ijb_2", incident="inc_2"))
    repo.delete_incident_data("inc_1")
    assert repo.get_intake_job("ijb_1") is None
    assert repo.list_intake_candidates("ijb_1") == []
    assert repo.get_intake_job("ijb_2") is not None
