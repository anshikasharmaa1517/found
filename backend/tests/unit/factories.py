from datetime import UTC, datetime

from found_core.domain.models import Claim, Subscription


def claim(
    seq: int,
    claim_type: str,
    reported_at: str | None,
    source_id: str = "src_police",
    subject_type: str = "PERSON",
) -> Claim:
    return Claim(
        id=f"clm_{seq}",
        incident_id="inc_1",
        subject_id="per_1",
        subject_type=subject_type,
        source_id=source_id,
        seq=seq,
        claim_type=claim_type,
        original_text="text",
        external_reference=f"REF-{seq}",
        reported_at=datetime.fromisoformat(reported_at) if reported_at else None,
        ingested_at=datetime(2026, 10, 5, tzinfo=UTC),
        extraction_method="structured_form",
        payload_hash=f"sha256:{seq}",
        created_by="user_1",
    )


def subscription(sms: bool = False, email: bool = False) -> Subscription:
    return Subscription(
        id="sub_1", subject_id="per_1", user_id="user_f", channel_sms=sms, channel_email=email
    )
