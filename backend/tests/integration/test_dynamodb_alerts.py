from datetime import UTC, datetime

from found_core.domain.enums import DeliveryStatus
from found_core.domain.models import Alert

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def stored(repo, status="PENDING"):
    repo.put_alert_if_absent(
        Alert(
            id="alr_1",
            incident_id="inc_1",
            subject_id="per_1",
            subscription_id="sub_1",
            claim_id="clm_1",
            user_id="fam_1",
            relation="UPDATE",
            severity="info",
            message="Newer report.",
            delivery_status=status,
            created_at=AT,
        )
    )


def test_only_one_caller_takes_a_pending_alert(repo):
    stored(repo)
    P, S = DeliveryStatus.PENDING, DeliveryStatus.SENDING
    assert repo.transition_alert("sub_1", "clm_1", P, S)
    assert not repo.transition_alert("sub_1", "clm_1", P, S)
    assert not repo.transition_alert("sub_x", "clm_1", P, S)


def test_the_outcome_is_stored_with_channels_note_and_time(repo):
    stored(repo, "SENDING")
    assert repo.transition_alert(
        "sub_1",
        "clm_1",
        DeliveryStatus.SENDING,
        DeliveryStatus.SENT,
        channels=("email",),
        note="SMS_NOT_ENABLED",
        at=AT,
    )
    alert = repo.get_alert("sub_1", "clm_1")
    assert alert.delivery_status == DeliveryStatus.SENT
    assert alert.delivered_channels == ("email",) and alert.delivery_note == "SMS_NOT_ENABLED"
    assert alert.delivered_at == AT
