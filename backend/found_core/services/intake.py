"""Uploads and pasted text to candidate claims, and reviewers' decisions on them.

Design Sections 5.3, 6.8 and 9.10. A publisher uploads a file straight to S3 with a
presigned form, or pastes text that the API stores the same way. The object's arrival
starts the intake workflow, which calls the steps below. Nothing becomes a claim until
a reviewer confirms it, and a confirmed candidate goes through the same ingest path as a
form report, as the uploader's organization (never one named in the document).
"""

import hashlib
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from found_core.domain.auth import ADMIN, PUBLISHER, REVIEWER, Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import (
    CandidateStatus,
    ExtractionMethod,
    IntakeStatus,
    ReviewItemType,
    SubjectType,
)
from found_core.domain.errors import (
    BadRequest,
    Forbidden,
    NotFound,
    ValidationFailed,
    VersionConflict,
)
from found_core.domain.ids import new_id, review_item_id
from found_core.domain.intake import (
    MAX_BYTES,
    MAX_TEXT_CHARS,
    TEXT_TYPE,
    UPLOAD_EXPIRES_SECONDS,
    ValidCandidate,
    check_content_type,
    intake_key,
    matches_type,
    parse_intake_key,
    parse_reported_at,
    validate_candidates,
)
from found_core.domain.models import IntakeCandidate, IntakeJob, Organization, ReviewItem
from found_core.domain.rules import REVIEW_PRIORITY
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.intake import CandidateExtractor, ExtractionFailed, ObjectStore, TextReader
from found_core.ports.repository import FoundRepository
from found_core.services.ingest import IngestService

NOTE_MAX = 500
FILENAME_MAX = 200
PASTED_NAME = "pasted.txt"
# One more try when the model's output is unusable, then the job fails (design 6.8).
_RETRY_ON = frozenset({"MODEL_INVALID_JSON", "MODEL_INVALID_OUTPUT", "MODEL_NO_TOOL_CALL"})
EDITABLE = frozenset({"subject_name", "age", "claim_type", "reported_at"})
DECISION_FIELDS = frozenset({"decision", "note", "person_id", "edits"})


@dataclass(frozen=True)
class UploadForm:
    job: IntakeJob
    post: dict[str, Any]


@dataclass(frozen=True)
class IntakeDetail:
    job: IntakeJob
    candidates: list[IntakeCandidate]


def _is_reviewer(caller: Caller) -> bool:
    return caller.has(REVIEWER) or caller.has(ADMIN)


class IntakeService:
    def __init__(
        self,
        repo: FoundRepository,
        ingest: IngestService,
        store: ObjectStore,
        reader: TextReader | None = None,
        extractor: CandidateExtractor | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repo = repo
        self._ingest = ingest
        self._store = store
        self._reader = reader
        self._extractor = extractor
        self._clock = clock or SystemClock()

    # Publisher side (API).

    def request_upload(self, caller: Caller, incident_id: str, body: dict[str, Any]) -> UploadForm:
        org = self._publisher_org(caller, incident_id)
        if set(body) - {"filename", "content_type", "purpose"}:
            raise BadRequest("The body may only hold filename, content_type and purpose.")
        if body.get("purpose", "INTAKE") != "INTAKE":
            raise BadRequest("purpose must be INTAKE.")
        filename = body.get("filename")
        if not isinstance(filename, str) or not filename.strip() or len(filename) > FILENAME_MAX:
            raise BadRequest(f"filename is required, at most {FILENAME_MAX} characters.")
        content_type = check_content_type(str(body.get("content_type", "")))
        job = self._new_job(caller, incident_id, org, filename.strip(), content_type)
        post = self._store.presign_post(job.s3_key, content_type, MAX_BYTES, UPLOAD_EXPIRES_SECONDS)
        return UploadForm(job=job, post=post)

    def submit_text(self, caller: Caller, incident_id: str, body: dict[str, Any]) -> IntakeJob:
        org = self._publisher_org(caller, incident_id)
        if set(body) - {"text"}:
            raise BadRequest("The body may only hold text.")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
            raise BadRequest(f"text is required, at most {MAX_TEXT_CHARS} characters.")
        job = self._new_job(caller, incident_id, org, PASTED_NAME, TEXT_TYPE)
        # Stored like an upload, so the same workflow picks it up.
        self._store.put_text(job.s3_key, text)
        return job

    def detail(self, caller: Caller, job_id: str) -> IntakeDetail:
        job = self._repo.get_intake_job(job_id)
        if job is None:
            raise NotFound("Intake job not found.", job_id=job_id)
        own = caller.has(PUBLISHER) and caller.org_id == job.organization_id
        if not (own or _is_reviewer(caller)):
            raise NotFound("Intake job not found.", job_id=job_id)
        return IntakeDetail(job=job, candidates=self._repo.list_intake_candidates(job_id))

    def _publisher_org(self, caller: Caller, incident_id: str) -> Organization:
        if not caller.has(PUBLISHER) or not caller.org_id:
            raise Forbidden("Only publishers can submit reports.")
        if not self._repo.incident_exists(incident_id):
            raise NotFound("Incident not found.", incident_id=incident_id)
        org = self._repo.get_organization(incident_id, caller.org_id)
        if org is None:
            raise Forbidden("Your organization is not registered for this incident.")
        return org

    def _new_job(
        self, caller: Caller, incident_id: str, org: Organization, filename: str, content_type: str
    ) -> IntakeJob:
        job_id = new_id("ijb")
        job = IntakeJob(
            id=job_id,
            incident_id=incident_id,
            organization_id=org.id,
            s3_key=intake_key(incident_id, job_id, filename),
            filename=filename,
            content_type=content_type,
            created_by=caller.user_id,
            created_at=self._clock.now(),
        )
        self._repo.put_intake_job(job)
        return job

    # Workflow steps.

    def validate_object(self, key: str) -> dict[str, Any]:
        """Check the stored object against its job. Returns the next step's input."""
        _, job_id = parse_intake_key(key)
        job = self._repo.get_intake_job(job_id)
        if job is None or job.s3_key != key:
            raise ExtractionFailed("JOB_NOT_FOUND")
        if job.status != IntakeStatus.RECEIVED:
            # S3 events can arrive twice; the first one already started this job.
            return {"job_id": job_id, "kind": "duplicate"}
        try:
            stored = self._store.read(key, MAX_BYTES)
        except ValueError:
            raise ExtractionFailed("TOO_LARGE") from None
        if stored.content_type != job.content_type:
            raise ExtractionFailed("TYPE_MISMATCH")
        if not matches_type(job.content_type, stored.data):
            raise ExtractionFailed("CONTENT_MISMATCH")
        self._repo.update_intake_job_if(
            job_id,
            (IntakeStatus.RECEIVED,),
            {
                "status": IntakeStatus.EXTRACTING,
                "sha256": hashlib.sha256(stored.data).hexdigest(),
                "size_bytes": stored.size,
                "updated_at": self._clock.now(),
            },
        )
        return {"job_id": job_id, "kind": "text" if job.content_type == TEXT_TYPE else "document"}

    def extract(self, job_id: str) -> dict[str, Any]:
        """Read the text, ask the model for candidates and keep the ones that hold up."""
        job = self._extracting(job_id)
        if job.content_type == TEXT_TYPE:
            text = self._store.read(job.s3_key, MAX_BYTES).data.decode("utf-8")
        else:
            if self._reader is None:
                raise ExtractionFailed("TEXT_READER_UNAVAILABLE")
            text = self._reader.read_text(job.s3_key)
        text = text.strip()[:MAX_TEXT_CHARS]
        if not text:
            raise ExtractionFailed("NO_TEXT")
        raw = self._ask_model(text)
        kept, dropped = validate_candidates(raw, text)
        self._repo.update_intake_job_if(
            job_id,
            (IntakeStatus.EXTRACTING,),
            {
                "extracted_text": text,
                "dropped_count": len(dropped),
                "updated_at": self._clock.now(),
            },
        )
        return {
            "job_id": job_id,
            "candidates": [c.model_dump(mode="json") for c in kept],
            "dropped": dropped,
        }

    def _ask_model(self, text: str) -> list[Any]:
        if self._extractor is None:
            raise ExtractionFailed("MODEL_UNAVAILABLE")
        try:
            return self._extractor.extract(text)
        except ExtractionFailed as err:
            if err.reason not in _RETRY_ON:
                raise
        return self._extractor.extract(text)

    def store(self, job_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Write the candidates and queue the job for review. Safe to repeat."""
        job = self._extracting(job_id)
        valid = [ValidCandidate.model_validate(c) for c in candidates]
        if not valid:
            raise ExtractionFailed("NO_CANDIDATES")
        self._repo.put_intake_candidates(
            [
                IntakeCandidate(
                    id=f"icd_{job.id.removeprefix('ijb_')}_{idx:03d}",
                    job_id=job.id,
                    incident_id=job.incident_id,
                    idx=idx,
                    subject_type=c.subject_type,
                    subject_name=c.subject_name,
                    age=c.age,
                    claim_type=c.claim_type,
                    reported_at=c.reported_at,
                    location_name=c.location_name,
                    span_text=c.span_text,
                )
                for idx, c in enumerate(valid)
            ]
        )
        item_type = ReviewItemType.INTAKE
        self._repo.put_review_item_if_absent(
            ReviewItem(
                id=review_item_id(item_type, job.id),
                incident_id=job.incident_id,
                item_type=item_type,
                ref_id=job.id,
                priority=REVIEW_PRIORITY[item_type],
                created_at=self._clock.now(),
            )
        )
        self._repo.update_intake_job_if(
            job_id,
            (IntakeStatus.EXTRACTING,),
            {
                "status": IntakeStatus.READY_FOR_REVIEW,
                "candidate_count": len(valid),
                "updated_at": self._clock.now(),
            },
        )
        return {"job_id": job_id, "status": IntakeStatus.READY_FOR_REVIEW.value}

    def mark_failed(self, job_id: str | None, reason: str) -> dict[str, Any]:
        if job_id:
            self._repo.update_intake_job_if(
                job_id,
                (IntakeStatus.RECEIVED, IntakeStatus.EXTRACTING),
                {
                    "status": IntakeStatus.FAILED,
                    "failure_reason": reason[:120],
                    "updated_at": self._clock.now(),
                },
            )
        return {"job_id": job_id, "status": IntakeStatus.FAILED.value, "reason": reason}

    def _extracting(self, job_id: str) -> IntakeJob:
        job = self._repo.get_intake_job(job_id)
        if job is None:
            raise ExtractionFailed("JOB_NOT_FOUND")
        if job.status != IntakeStatus.EXTRACTING:
            raise ExtractionFailed(f"JOB_{job.status}")
        return job

    # Reviewer side (API).

    def decide(self, caller: Caller, candidate_id: str, body: dict[str, Any]) -> IntakeCandidate:
        """Confirm (optionally edited, optionally about a known person) or reject."""
        if not _is_reviewer(caller):
            raise Forbidden("Only reviewers can confirm extracted reports.")
        if set(body) - DECISION_FIELDS:
            raise BadRequest("The body may only hold " + ", ".join(sorted(DECISION_FIELDS)) + ".")
        decision = body.get("decision")
        if decision not in (CandidateStatus.CONFIRMED, CandidateStatus.REJECTED):
            raise BadRequest("decision is required: CONFIRMED or REJECTED.")
        note = _note(body.get("note"))
        candidate = self._repo.get_intake_candidate(candidate_id)
        if candidate is None:
            raise NotFound("Candidate not found.", candidate_id=candidate_id)
        if candidate.status != CandidateStatus.PENDING_REVIEW:
            raise VersionConflict("This candidate was already decided.")
        job = self._repo.get_intake_job(candidate.job_id)
        if job is None:
            raise NotFound("Intake job not found.", job_id=candidate.job_id)

        changes: dict[str, Any] = {
            "status": CandidateStatus(decision),
            "decided_by": caller.user_id,
            "decided_at": self._clock.now(),
            "note": note,
        }
        if decision == CandidateStatus.CONFIRMED:
            edited = _apply_edits(candidate, body.get("edits"))
            claim = self._publish(caller, job, edited, body.get("person_id"))
            changes.update(edited.model_dump(include=EDITABLE - {"reported_at"}))
            changes.update(
                reported_at=edited.reported_at, claim_id=claim.id, subject_id=claim.subject_id
            )
        elif body.get("edits") or body.get("person_id"):
            raise BadRequest("Edits and a person apply only when confirming.")

        decided = candidate.model_copy(update=changes)
        if not self._repo.save_candidate_decision(decided):
            raise VersionConflict("This candidate was already decided.")
        self._close_review_if_done(job, caller, note)
        return decided

    def _publish(
        self, caller: Caller, job: IntakeJob, candidate: IntakeCandidate, person_id: Any
    ) -> Any:
        org = self._repo.get_organization(job.incident_id, job.organization_id)
        if org is None:
            raise BadRequest("The uploading organization is no longer registered.")
        if person_id is not None:
            # Attaching to a known record is the reviewer's explicit choice, never a match
            # made from the name (product rule 6).
            person = self._repo.get_subject(str(person_id))
            if (
                person is None
                or person.incident_id != job.incident_id
                or person.subject_type != candidate.subject_type
            ):
                raise ValidationFailed("person_id must be a record of the same kind here.")
            subject: dict[str, Any] = {"type": candidate.subject_type, "id": person.id}
        else:
            new: dict[str, Any] = {"name": candidate.subject_name}
            if candidate.age is not None and candidate.subject_type == SubjectType.PERSON:
                new["age"] = candidate.age
            subject = {"type": candidate.subject_type, "new": new}
        reported = candidate.reported_at.isoformat() if candidate.reported_at else None
        location = (
            {"location": {"name": candidate.location_name}} if candidate.location_name else {}
        )
        cmd = PublishCommand.parse(
            {
                "incident_id": job.incident_id,
                "org_id": org.id,
                "org_name": org.name,
                "org_type": org.org_type,
                "actor": caller.user_id,
                "subject": subject,
                "claim_type": candidate.claim_type,
                "original_text": candidate.span_text,
                "external_reference": f"INTAKE-{job.id}-{candidate.idx}",
                "reported_at": reported,
                **location,
                "extraction_method": ExtractionMethod.INTAKE_CONFIRMED,
            }
        )
        return self._ingest.publish(cmd).claim

    def _close_review_if_done(self, job: IntakeJob, caller: Caller, note: str | None) -> None:
        candidates = self._repo.list_intake_candidates(job.id)
        if any(c.status == CandidateStatus.PENDING_REVIEW for c in candidates):
            return
        self._repo.resolve_review_item(
            job.incident_id,
            review_item_id(ReviewItemType.INTAKE, job.id),
            caller.user_id,
            note,
            self._clock.now(),
        )


def _note(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw.strip()) > NOTE_MAX:
        raise BadRequest(f"note must be text of at most {NOTE_MAX} characters.")
    return raw.strip() or None


def _apply_edits(candidate: IntakeCandidate, raw: Any) -> IntakeCandidate:
    if raw is None:
        return candidate
    if not isinstance(raw, dict) or set(raw) - EDITABLE:
        raise BadRequest("edits may only hold " + ", ".join(sorted(EDITABLE)) + ".")
    changes = dict(raw)
    if "reported_at" in changes:
        value = changes["reported_at"]
        parsed = parse_reported_at(value) if isinstance(value, str) else None
        if value is not None and parsed is None:
            raise BadRequest("reported_at must be ISO 8601 with a UTC offset, or null.")
        changes["reported_at"] = parsed
    try:
        return IntakeCandidate.model_validate({**candidate.model_dump(), **changes})
    except ValidationError:
        raise BadRequest("edits are invalid.") from None
