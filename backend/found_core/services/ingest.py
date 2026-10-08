"""Single write path for claims: structured reports, confirmed intake, fixtures, imports."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from found_core.domain.commands import PublishCommand
from found_core.domain.enums import SUBJECT_ID_PREFIX
from found_core.domain.errors import (
    NotFound,
    ReferenceConflict,
    ServiceUnavailable,
    ValidationFailed,
)
from found_core.domain.hashing import payload_hash
from found_core.domain.ids import new_id, source_id
from found_core.domain.models import Claim, IdemMarker, Source, Subject
from found_core.domain.normalize import detect_mentions, normalize_text
from found_core.ports.clock import Clock, SystemClock
from found_core.ports.repository import (
    FoundRepository,
    IdempotencyConflict,
    PublishPlan,
    SequenceConflict,
)


@dataclass(frozen=True)
class PublishResult:
    claim: Claim
    replayed: bool


def _jitter(attempt: int) -> float:
    return random.uniform(0, min(0.4, 0.02 * 2**attempt))


class IngestService:
    def __init__(
        self,
        repo: FoundRepository,
        clock: Clock | None = None,
        id_factory: Callable[[str], str] = new_id,
        sleep: Callable[[float], None] = time.sleep,
        max_seq_retries: int = 5,
    ) -> None:
        self._repo = repo
        self._clock = clock or SystemClock()
        self._new_id = id_factory
        self._sleep = sleep
        self._max_seq_retries = max_seq_retries

    def publish(self, cmd: PublishCommand) -> PublishResult:
        if not self._repo.incident_exists(cmd.incident_id):
            raise NotFound("Incident not found.", incident_id=cmd.incident_id)
        digest = payload_hash(cmd.payload())

        existing = self._repo.get_idempotency(cmd.org_id, cmd.external_reference)
        if existing is not None:
            return self._replay_or_conflict(existing, digest)

        source = self._repo.ensure_source(self._source_for(cmd))
        mentions = detect_mentions(
            cmd.original_text, self._repo.list_sources(cmd.incident_id), exclude_id=source.id
        )
        claim_id = self._new_id("clm")
        new_subject_id = (
            self._new_id(SUBJECT_ID_PREFIX[cmd.subject.type]) if cmd.subject.new else None
        )

        for attempt in range(self._max_seq_retries):
            subject, is_new = self._resolve_subject(cmd, new_subject_id)
            next_seq = subject.claim_seq + 1
            claim = Claim(
                id=claim_id,
                incident_id=cmd.incident_id,
                subject_id=subject.id,
                subject_type=subject.subject_type,
                source_id=source.id,
                seq=next_seq,
                claim_type=cmd.claim_type,
                value=cmd.value,
                original_text=cmd.original_text,
                external_reference=cmd.external_reference,
                reported_at=cmd.reported_at_utc(),
                reported_at_raw=cmd.reported_at,
                ingested_at=self._clock.now(),
                extraction_method=cmd.extraction_method,
                payload_hash=digest,
                mentioned_source_ids=tuple(m.id for m in mentions),
                created_by=cmd.actor,
            )
            plan = PublishPlan(
                marker=IdemMarker(
                    org_id=cmd.org_id,
                    external_reference=cmd.external_reference,
                    claim_id=claim_id,
                    payload_hash=digest,
                ),
                subject=subject.model_copy(update={"claim_seq": next_seq}),
                expected_seq=subject.claim_seq,
                create_subject=is_new,
                claim=claim,
                name_tokens=tuple(subject.tokens()) if is_new else (),
            )
            try:
                return PublishResult(self._repo.publish_claim_tx(plan), replayed=False)
            except IdempotencyConflict:
                marker = self._repo.get_idempotency(cmd.org_id, cmd.external_reference)
                if marker is None:  # pragma: no cover - marker vanished, only on reset
                    raise ServiceUnavailable("Idempotency marker missing.") from None
                return self._replay_or_conflict(marker, digest)
            except SequenceConflict:
                self._sleep(_jitter(attempt))
        raise ServiceUnavailable("Too much contention on this subject.", code="SEQUENCE")

    def _replay_or_conflict(self, marker: IdemMarker, digest: str) -> PublishResult:
        if marker.payload_hash != digest:
            raise ReferenceConflict(
                "Reference already used with different content.",
                existing_claim_id=marker.claim_id,
            )
        claim = self._repo.get_claim(marker.claim_id)
        if claim is None:  # pragma: no cover - only on reset
            raise ServiceUnavailable("Claim for reference missing.")
        return PublishResult(claim, replayed=True)

    @staticmethod
    def _source_for(cmd: PublishCommand) -> Source:
        name_norm = normalize_text(cmd.org_name)
        return Source(
            id=source_id(cmd.incident_id, name_norm),
            incident_id=cmd.incident_id,
            name=cmd.org_name,
            name_norm=name_norm,
            source_type=cmd.org_type,
            organization_id=cmd.org_id,
        )

    def _resolve_subject(
        self, cmd: PublishCommand, new_subject_id: str | None
    ) -> tuple[Subject, bool]:
        if cmd.subject.id is not None:
            subject = self._repo.get_subject(cmd.subject.id)
            if subject is None or subject.incident_id != cmd.incident_id:
                raise NotFound("Subject not found in this incident.", subject_id=cmd.subject.id)
            if subject.subject_type != cmd.subject.type:
                raise ValidationFailed("Subject type does not match.", subject_id=subject.id)
            return subject, False
        new = cmd.subject.new
        assert new is not None and new_subject_id is not None
        return (
            Subject(
                id=new_subject_id,
                incident_id=cmd.incident_id,
                subject_type=cmd.subject.type,
                display_name=new.name,
                name_norm=normalize_text(new.name),
                age=new.age,
                notes=new.notes,
            ),
            True,
        )
