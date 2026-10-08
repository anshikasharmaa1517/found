from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.commands import PublishCommand
from found_core.domain.errors import NotFound, ReferenceConflict, ValidationFailed
from found_core.services.ingest import IngestService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}


def cmd(org=POLICE, ref="REF-1", subject=None, **overrides) -> PublishCommand:
    data = {
        "incident_id": "inc_1",
        **org,
        "actor": "user_1",
        "subject": subject or {"type": "PERSON", "new": {"name": "Maya Rawat", "age": 24}},
        "claim_type": "MISSING",
        "original_text": "Maya Rawat, 24, missing since the bridge collapse.",
        "external_reference": ref,
        "reported_at": "2026-10-02T21:10:00+05:30",
        **overrides,
    }
    return PublishCommand.parse(data)


@pytest.fixture
def repo():
    r = InMemoryFoundRepository()
    r.add_incident("inc_1")
    return r


@pytest.fixture
def service(repo):
    return IngestService(repo, clock=FixedClock(), sleep=lambda _: None)


def person(subject_id):
    return {"type": "PERSON", "id": subject_id}


def test_first_report_creates_subject_source_and_claim(service, repo):
    result = service.publish(cmd())
    claim = result.claim
    assert not result.replayed
    assert claim.seq == 1
    subject = repo.get_subject(claim.subject_id)
    assert subject.claim_seq == 1 and subject.display_name == "Maya Rawat"
    assert not hasattr(subject, "status")
    assert repo.sources[claim.source_id].name == "District Police Demo"
    assert repo.name_tokens["rawat"] == {subject.id}


def test_reports_about_one_subject_get_increasing_sequence(service):
    first = service.publish(cmd()).claim
    second = service.publish(
        cmd(org=HOSPITAL, ref="CH-1", subject=person(first.subject_id), claim_type="FOUND_SAFE")
    ).claim
    assert second.seq == 2 and second.subject_id == first.subject_id


def test_same_reference_and_content_replays(service, repo):
    first = service.publish(cmd())
    again = service.publish(cmd())
    assert again.replayed and again.claim.id == first.claim.id
    assert len(repo.claims) == 1 and len(repo.subjects) == 1


def test_same_reference_different_content_conflicts(service):
    service.publish(cmd())
    with pytest.raises(ReferenceConflict):
        service.publish(cmd(original_text="Different text."))


def test_same_reference_from_another_org_is_independent(service, repo):
    service.publish(cmd(org=POLICE))
    service.publish(cmd(org=HOSPITAL))
    assert len(repo.claims) == 2


def test_original_fields_are_preserved(service):
    claim = service.publish(cmd()).claim
    assert claim.reported_at_raw == "2026-10-02T21:10:00+05:30"
    assert claim.reported_at == datetime(2026, 10, 2, 15, 40, tzinfo=UTC)
    assert claim.ingested_at == datetime(2026, 10, 5, 10, 15, tzinfo=UTC)
    assert claim.extraction_method == "structured_form"
    assert claim.external_reference == "REF-1"


def test_mentions_are_detected_and_exclude_own_source(service):
    hospital_claim = service.publish(cmd(org=HOSPITAL, ref="CH-1", claim_type="FOUND_SAFE")).claim
    relay = service.publish(
        cmd(
            org=NGO,
            ref="NGO-1",
            subject=person(hospital_claim.subject_id),
            claim_type="FOUND_SAFE",
            original_text="According to Central Hospital Demo, Maya R. was admitted.",
        )
    ).claim
    assert relay.mentioned_source_ids == (hospital_claim.source_id,)


def test_unknown_incident_or_subject_is_not_found(service):
    with pytest.raises(NotFound):
        service.publish(cmd(incident_id="inc_missing"))
    with pytest.raises(NotFound):
        service.publish(cmd(subject=person("per_missing")))


def test_subject_type_mismatch_is_rejected(service):
    first = service.publish(cmd()).claim
    with pytest.raises(ValidationFailed):
        service.publish(
            cmd(
                ref="R2",
                subject={"type": "SHELTER", "id": first.subject_id},
                claim_type="SHELTER_OPEN",
            )
        )


def test_concurrent_publishes_get_unique_contiguous_sequences(repo):
    service = IngestService(repo, clock=FixedClock(), sleep=lambda _: None, max_seq_retries=200)
    subject_id = service.publish(cmd()).claim.subject_id

    def publish(i):
        return service.publish(
            cmd(org=HOSPITAL, ref=f"CH-{i}", subject=person(subject_id), claim_type="FOUND_SAFE")
        ).claim.seq

    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = sorted(pool.map(publish, range(30)))
    assert seqs == list(range(2, 32))


def test_concurrent_retries_of_one_report_create_one_claim(repo):
    service = IngestService(repo, clock=FixedClock(), sleep=lambda _: None, max_seq_retries=50)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.publish(cmd()), range(16)))
    assert len({r.claim.id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert len(repo.claims) == 1
