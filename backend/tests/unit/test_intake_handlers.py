import json

import pytest

from found_core import container
from found_core.domain.cursor import CursorCodec
from found_core.domain.models import Organization
from found_core.services.ingest import IngestService
from found_core.services.intake import IntakeService
from found_core.services.review import ReviewService
from handlers import intake as intake_handler
from tests.unit.test_api_handler import FixedClock, call, event
from tests.unit.test_api_handler import repo as api_repo  # noqa: F401 - fixture
from tests.unit.test_intake import KAVITA, ROAD, TEXT, FakeExtractor, FakeReader, FakeStore
from tests.unit.test_watcher_handler import Context

PUBLISHER = {"sub": "pub_1", "cognito:groups": "[publisher]", "custom:org_id": "org_h"}
REVIEWER = {"sub": "rev_1", "cognito:groups": "[reviewer]"}
FAMILY = {"sub": "fam_1", "cognito:groups": "[family]"}


@pytest.fixture
def world(api_repo, monkeypatch):  # noqa: F811
    store = FakeStore()
    service = IntakeService(
        api_repo,
        IngestService(api_repo, clock=FixedClock(), sleep=lambda _: None),
        store,
        FakeReader(),
        FakeExtractor([KAVITA, ROAD]),
        clock=FixedClock(),
    )
    monkeypatch.setattr(container, "intake_service", lambda: service)
    review = ReviewService(api_repo, CursorCodec(b"k" * 32))
    monkeypatch.setattr(container, "review_service", lambda: review)
    return api_repo, store


def step(**payload):
    return intake_handler.handler(payload, Context())


def run_workflow(key):
    validated = step(step="validate", key=key)
    extracted = step(step="extract", job_id=validated["job_id"])
    return step(step="store", job_id=validated["job_id"], candidates=extracted["candidates"])


def test_upload_returns_a_presigned_form(world):
    body = {"filename": "list.jpg", "content_type": "image/jpeg"}
    status, created, _ = call(event("POST", "/v1/incidents/inc_1/uploads", body, PUBLISHER))
    assert status == 201 and created["upload_id"].startswith("ijb_")
    assert created["post"]["fields"]["key"].endswith(f"{created['upload_id']}/list.jpg")
    assert created["max_bytes"] == 5 * 1024 * 1024 and created["expires_in"] == 300
    assert call(event("POST", "/v1/incidents/inc_1/uploads", body, REVIEWER))[0] == 403


def test_pasted_text_runs_through_the_workflow_to_the_review_queue(world):
    repo, store = world
    status, body, _ = call(
        event("POST", "/v1/incidents/inc_1/intake-text", {"text": TEXT}, PUBLISHER)
    )
    assert status == 202 and body["job"]["status"] == "RECEIVED"
    job_id = body["job"]["id"]
    key = repo.get_intake_job(job_id).s3_key
    assert key in store.objects

    assert run_workflow(key) == {"job_id": job_id, "status": "READY_FOR_REVIEW"}

    status, detail, _ = call(event("GET", f"/v1/intake-jobs/{job_id}", claims=PUBLISHER))
    assert status == 200 and detail["job"]["candidate_count"] == 2
    assert [c["subject_name"] for c in detail["candidates"]] == [
        "Kavita Bisht",
        "Road to Upper Village",
    ]
    assert call(event("GET", f"/v1/intake-jobs/{job_id}", claims=FAMILY))[0] == 404

    status, queue, _ = call(
        event("GET", "/v1/incidents/inc_1/review-queue", claims=REVIEWER, query={"type": "intake"})
    )
    (item,) = queue["items"]
    assert item["intake"]["job"]["id"] == job_id and item["intake"]["extracted_text"] == TEXT
    candidate = item["intake"]["candidates"][0]

    path = f"/v1/intake-candidates/{candidate['id']}/decision"
    status, decided, _ = call(event("POST", path, {"decision": "CONFIRMED"}, REVIEWER))
    assert status == 200 and decided["candidate"]["status"] == "CONFIRMED"
    claim = repo.get_claim(decided["candidate"]["claim_id"])
    assert claim.extraction_method == "textract+bedrock, human-confirmed"
    assert call(event("POST", path, {"decision": "REJECTED"}, REVIEWER))[0] == 409


def test_a_failed_step_records_its_reason(world):
    repo, store = world
    _, body, _ = call(event("POST", "/v1/incidents/inc_1/intake-text", {"text": TEXT}, PUBLISHER))
    key = repo.get_intake_job(body["job"]["id"]).s3_key
    cause = json.dumps({"errorType": "ExtractionFailed", "errorMessage": "MODEL_HTTP_403"})
    result = step(step="fail", key=key, error={"Error": "ExtractionFailed", "Cause": cause})
    assert result["reason"] == "MODEL_HTTP_403"
    job = repo.get_intake_job(body["job"]["id"])
    assert job.status == "FAILED" and job.failure_reason == "MODEL_HTTP_403"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ({"Error": "States.Timeout", "Cause": ""}, "States.Timeout"),
        ({"Error": "ClientError", "Cause": "{not json"}, "ClientError"),
        (None, "UNKNOWN"),
    ],
)
def test_other_errors_are_recorded_by_type(error, reason):
    assert intake_handler._reason(error) == reason


def test_a_failure_for_an_unknown_key_changes_nothing(world):
    assert step(step="fail", key="media/x", error=None)["job_id"] is None


def test_unknown_steps_are_errors(world):
    with pytest.raises(ValueError):
        step(step="publish")


def test_upload_needs_a_registered_org(world, api_repo):  # noqa: F811
    api_repo.add_organization(
        Organization(
            id="org_x",
            incident_id="inc_2",
            name="Elsewhere",
            name_norm="elsewhere",
            org_type="NGO",
        )
    )
    other = {**PUBLISHER, "custom:org_id": "org_x"}
    body = {"filename": "a.png", "content_type": "image/png"}
    assert call(event("POST", "/v1/incidents/inc_1/uploads", body, other))[0] == 403
