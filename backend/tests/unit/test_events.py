import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from boto3.dynamodb.types import TypeSerializer

from found_core.adapters.dynamodb import (
    alert_item,
    claim_item,
    marker_item,
    review_item_item,
    subject_item,
)
from found_core.domain.models import Alert, IdemMarker, ReviewItem, Subject
from found_core.events import (
    EVENT_DETAIL_TYPE,
    EVENT_MODELS,
    EVENT_SOURCE,
    AlertCreated,
    AlertReleased,
    ClaimCreated,
    InvestigationStepCreated,
    InvestigationUpdated,
    NotADomainEvent,
    ReviewCreated,
    SubjectCreated,
    from_attribute,
    from_bus_event,
    from_stream,
)

from .factories import claim

DOCS = Path(__file__).resolve().parents[3] / "docs" / "events"
_serializer = TypeSerializer()


def record(item, event_name="INSERT"):
    image = {k: _serializer.serialize(v) for k, v in item.items()}
    return {
        "eventID": "evt-1",
        "eventName": event_name,
        "dynamodb": {
            "ApproximateCreationDateTime": 1791195322,
            "Keys": {"PK": image["PK"], "SK": image["SK"]},
            "NewImage": image,
        },
    }


def envelope(detail):
    return {"source": EVENT_SOURCE, "detail-type": EVENT_DETAIL_TYPE, "detail": detail}


SUBJECT = Subject(
    id="per_1",
    incident_id="inc_1",
    subject_type="PERSON",
    display_name="Maya Rawat",
    name_norm="maya rawat",
    age=24,
    claim_seq=1,
)


def test_claim_insert_becomes_claim_created():
    event = from_bus_event(envelope(record(claim_item(claim(2, "FOUND_SAFE", None)))))
    assert event == ClaimCreated(
        event_id="evt-1",
        incident_id="inc_1",
        subject_id="per_1",
        subject_type="PERSON",
        claim_id="clm_2",
        seq=2,
        source_id="src_police",
        occurred_at=datetime(2026, 10, 5, tzinfo=UTC),
    )


def test_subject_insert_becomes_subject_created_at_stream_time():
    event = from_stream(record(subject_item(SUBJECT)))
    assert isinstance(event, SubjectCreated)
    assert event.subject_id == "per_1" and event.subject_type == "PERSON"
    assert event.occurred_at == datetime.fromtimestamp(1791195322, tz=UTC)


def test_modify_and_other_entities_are_ignored():
    assert from_stream(record(subject_item(SUBJECT), event_name="MODIFY")) is None
    assert from_stream(record(subject_item(SUBJECT), event_name="REMOVE")) is None
    marker = IdemMarker(org_id="o", external_reference="r", claim_id="c", payload_hash="h")
    assert from_stream(record(marker_item(marker))) is None


@pytest.mark.parametrize(
    "event",
    [
        {"source": "aws.s3", "detail-type": EVENT_DETAIL_TYPE, "detail": {}},
        {"source": EVENT_SOURCE, "detail-type": "other", "detail": {}},
        {"source": EVENT_SOURCE, "detail-type": EVENT_DETAIL_TYPE},
    ],
)
def test_foreign_envelopes_are_rejected(event):
    with pytest.raises(NotADomainEvent):
        from_bus_event(event)


def test_incomplete_claim_image_fails_loudly():
    item = claim_item(claim(1, "MISSING", None))
    del item["source_id"]
    with pytest.raises(KeyError):
        from_stream(record(item))


@pytest.mark.parametrize(
    "value",
    [
        "text",
        7,
        Decimal("1.5"),
        True,
        None,
        [1, "a", [False]],
        {"m": {"n": 2}},
        {"a", "b"},
        {Decimal(1), Decimal(2)},
    ],
)
def test_attribute_conversion_round_trips(value):
    assert from_attribute(_serializer.serialize(value)) == value


@pytest.mark.parametrize("bad", [{}, {"S": "a", "N": "1"}, {"X": "1"}])
def test_malformed_attributes_are_rejected(bad):
    with pytest.raises(NotADomainEvent):
        from_attribute(bad)


@pytest.mark.parametrize("model", EVENT_MODELS, ids=lambda m: m.__name__)
def test_published_schema_matches_model(model):
    """Set UPDATE_EVENT_SCHEMAS=1 to rewrite docs/events after a deliberate change."""
    name = model.model_fields["type"].default
    path = DOCS / f"{name}.schema.json"
    schema = model.model_json_schema()
    if os.environ.get("UPDATE_EVENT_SCHEMAS") == "1":
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    published = json.loads(path.read_text(encoding="utf-8"))
    assert published == schema, f"{path.name} is out of date, see this test's docstring"


WHEN = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


def test_alert_insert_becomes_alert_created():
    alert = Alert(
        id="alr_1",
        incident_id="inc_1",
        subject_id="per_1",
        subscription_id="sub_1",
        claim_id="clm_1",
        user_id="fam_1",
        relation="UPDATE",
        severity="high",
        message="Newer report.",
        delivery_status="HELD",
        held_reason="SENSITIVE_STATUS",
        created_at=WHEN,
    )
    assert from_stream(record(alert_item(alert))) == AlertCreated(
        event_id="evt-1",
        incident_id="inc_1",
        alert_id="alr_1",
        user_id="fam_1",
        subject_id="per_1",
        subscription_id="sub_1",
        claim_id="clm_1",
        severity="high",
        message="Newer report.",
        delivery_status="HELD",
        occurred_at=WHEN,
    )


def test_review_insert_becomes_review_created():
    item = ReviewItem(
        id="rev_1",
        incident_id="inc_1",
        item_type="held_alert",
        ref_id="clm_1",
        subject_id="per_1",
        priority=1,
        created_at=WHEN,
    )
    event = from_stream(record(review_item_item(item)))
    assert isinstance(event, ReviewCreated)
    assert (event.review_id, event.item_type, event.priority) == ("rev_1", "held_alert", 1)


def _investigation_item(status):
    from found_core.adapters.dynamodb import investigation_item
    from found_core.domain.models import Investigation

    return investigation_item(
        Investigation(
            id="inv_1",
            incident_id="inc_1",
            claim_id="clm_1",
            fingerprint="fp_1",
            mode="LIVE",
            status=status,
            model_id="model-a",
            prompt_version="lineage-v1",
            agent_version="0.1.0",
            created_by="rev_1",
            queued_at=WHEN,
            finished_at=WHEN if status in ("COMPLETED", "NEEDS_REVIEW") else None,
        )
    )


def modify(old, new):
    rec = record(new, event_name="MODIFY")
    rec["dynamodb"]["OldImage"] = {k: _serializer.serialize(v) for k, v in old.items()}
    return rec


def test_step_insert_becomes_investigation_step():
    from found_core.adapters.dynamodb import investigation_step_item
    from found_core.domain.models import InvestigationStep

    step = InvestigationStep(
        investigation_id="inv_1",
        incident_id="inc_1",
        seq=2,
        kind="TOOL",
        tool_name="get_report",
        output_summary="Read report clm_1 from Flood Relief Demo",
        created_at=WHEN,
    )
    assert from_stream(record(investigation_step_item(step))) == InvestigationStepCreated(
        event_id="evt-1",
        incident_id="inc_1",
        investigation_id="inv_1",
        seq=2,
        kind="TOOL",
        tool_name="get_report",
        summary="Read report clm_1 from Flood Relief Demo",
        occurred_at=WHEN,
    )


def test_status_change_becomes_investigation_updated():
    event = from_stream(modify(_investigation_item("RUNNING"), _investigation_item("NEEDS_REVIEW")))
    assert isinstance(event, InvestigationUpdated)
    assert (event.investigation_id, event.claim_id) == ("inv_1", "clm_1")
    assert event.status == "NEEDS_REVIEW"


def test_counter_update_without_status_change_is_ignored():
    running = _investigation_item("RUNNING")
    assert from_stream(modify(running, {**running, "tool_calls": 3})) is None
    assert from_stream(modify(subject_item(SUBJECT), subject_item(SUBJECT))) is None


def _alert(status: str) -> dict:
    return alert_item(
        Alert(
            id="alr_1",
            incident_id="inc_1",
            subject_id="per_1",
            subscription_id="sub_1",
            claim_id="clm_1",
            user_id="fam_1",
            relation="UPDATE",
            severity="high",
            message="A sensitive report was received.",
            delivery_status=status,
            created_at=WHEN,
        )
    )


def _modify(old: dict, new: dict) -> dict:
    rec = record(new, event_name="MODIFY")
    rec["dynamodb"]["OldImage"] = {k: _serializer.serialize(v) for k, v in old.items()}
    return rec


def test_a_released_held_alert_becomes_alert_released():
    event = from_stream(_modify(_alert("HELD"), _alert("PENDING")))
    assert event == AlertReleased(
        event_id="evt-1",
        incident_id="inc_1",
        alert_id="alr_1",
        user_id="fam_1",
        subject_id="per_1",
        subscription_id="sub_1",
        claim_id="clm_1",
        occurred_at=datetime.fromtimestamp(1791195322, tz=UTC),
    )


@pytest.mark.parametrize(
    "old, new",
    [("PENDING", "SENDING"), ("SENDING", "SENT"), ("HELD", "NOT_REQUIRED"), ("HELD", "HELD")],
)
def test_other_alert_changes_are_not_events(old, new):
    assert from_stream(_modify(_alert(old), _alert(new))) is None
