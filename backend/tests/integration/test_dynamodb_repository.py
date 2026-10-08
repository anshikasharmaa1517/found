from datetime import UTC, datetime

import pytest
from boto3.dynamodb.conditions import Key

from found_core.adapters.dynamodb import organization_item, subscription_item
from found_core.domain.commands import PublishCommand
from found_core.domain.errors import ReferenceConflict
from found_core.domain.models import (
    Alert,
    Claim,
    Connection,
    IdemMarker,
    Location,
    Organization,
    ReviewItem,
    Source,
    Subject,
    Subscription,
)
from found_core.ports.repository import (
    IdempotencyConflict,
    NamePosition,
    PublishPlan,
    SequenceConflict,
)
from found_core.services.ingest import IngestService


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


HOSPITAL = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}
POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
NGO = {"org_id": "org_n", "org_name": "Flood Relief Demo", "org_type": "NGO"}

SOURCE = Source(
    id="src_police",
    incident_id="inc_1",
    name="District Police Demo",
    name_norm="district police demo",
    source_type="POLICE",
    organization_id="org_p",
)


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


def person(subject_id):
    return {"type": "PERSON", "id": subject_id}


def subject(seq=1):
    return Subject(
        id="per_1",
        incident_id="inc_1",
        subject_type="PERSON",
        display_name="Maya Rawat",
        name_norm="maya rawat",
        age=24,
        claim_seq=seq,
    )


def claim(seq=1, claim_id=None, source_id="src_police", mentions=()):
    return Claim(
        id=claim_id or f"clm_{seq}",
        incident_id="inc_1",
        subject_id="per_1",
        subject_type="PERSON",
        source_id=source_id,
        seq=seq,
        claim_type="MISSING",
        original_text="text",
        external_reference=f"REF-{seq}",
        reported_at=datetime(2026, 10, 2, 15, 40, tzinfo=UTC),
        ingested_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
        extraction_method="structured_form",
        payload_hash=f"sha256:{seq}",
        mentioned_source_ids=mentions,
        created_by="user_1",
    )


def plan(seq=1, ref=None, expected=None, create=None, tokens=(), **claim_kwargs):
    c = claim(seq, **claim_kwargs)
    return PublishPlan(
        marker=IdemMarker(
            org_id="org_p",
            external_reference=ref or c.external_reference,
            claim_id=c.id,
            payload_hash=c.payload_hash,
        ),
        subject=subject(seq),
        expected_seq=seq - 1 if expected is None else expected,
        create_subject=seq == 1 if create is None else create,
        claim=c,
        name_tokens=tokens,
    )


@pytest.fixture
def service(repo):
    return IngestService(repo, clock=FixedClock(), sleep=lambda _: None)


def test_incident_exists(repo):
    assert repo.incident_exists("inc_1")
    assert not repo.incident_exists("inc_missing")


def test_get_organization_is_scoped_to_incident(repo, table):
    org = Organization(
        id="org_h",
        incident_id="inc_1",
        name="Central Hospital Demo",
        name_norm="central hospital demo",
        org_type="HOSPITAL",
    )
    table.put_item(Item=organization_item(org))
    assert repo.get_organization("inc_1", "org_h") == org
    assert repo.get_organization("inc_2", "org_h") is None
    assert repo.get_organization("inc_1", "org_other") is None


def test_ensure_source_is_put_if_absent(repo):
    assert repo.ensure_source(SOURCE) == SOURCE
    renamed = SOURCE.model_copy(update={"name": "Other"})
    assert repo.ensure_source(renamed) == SOURCE
    assert repo.list_sources("inc_1") == [SOURCE]
    assert repo.list_sources("inc_2") == []


def test_publish_writes_items_under_design_keys(repo, table):
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan(tokens=("maya", "rawat"), mentions=("src_hosp",)))

    claim_item = table.get_item(Key={"PK": "SUBJ#per_1", "SK": "CLM#0000000001"})["Item"]
    assert claim_item["GSI1PK"] == "INC#inc_1#CLAIM"
    assert claim_item["GSI1SK"] == "2026-10-05T10:15:00Z#clm_1"
    assert claim_item["GSI2PK"] == "SRC#src_police"
    assert claim_item["GSI2SK"] == "2026-10-02T15:40:00Z#clm_1"
    assert claim_item["GSI3PK"] == "CLAIM#clm_1"
    assert claim_item["entity_type"] == "CLAIM"

    subject_item = table.get_item(Key={"PK": "SUBJ#per_1", "SK": "META"})["Item"]
    assert subject_item["GSI1PK"] == "INC#inc_1#PERSON"
    assert subject_item["GSI1SK"] == "maya rawat#per_1"
    assert "status" not in subject_item

    assert "Item" in table.get_item(Key={"PK": "IDEM#org_p#REF-1", "SK": "META"})
    assert "Item" in table.get_item(Key={"PK": "SRCMENT#src_hosp", "SK": "CLM#clm_1"})
    tokens = table.query(KeyConditionExpression=Key("PK").eq("NTOK#inc_1"))["Items"]
    assert sorted(t["SK"] for t in tokens) == ["maya#per_1", "rawat#per_1"]


def test_unknown_reported_time_sorts_first_by_source(repo, table):
    repo.ensure_source(SOURCE)
    p = plan()
    repo.publish_claim_tx(
        PublishPlan(**{**p.__dict__, "claim": p.claim.model_copy(update={"reported_at": None})})
    )
    item = table.get_item(Key={"PK": "SUBJ#per_1", "SK": "CLM#0000000001"})["Item"]
    assert item["GSI2SK"] == "0#clm_1"


def test_published_claim_round_trips(repo):
    repo.ensure_source(SOURCE)
    written = repo.publish_claim_tx(plan(mentions=("src_hosp",)))
    assert repo.get_claim("clm_1") == written
    assert repo.get_claim("clm_missing") is None
    assert repo.get_subject("per_1") == subject(1)
    assert repo.get_subject("per_missing") is None


def test_existing_subject_advances_sequence(repo):
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan(1))
    repo.publish_claim_tx(plan(2))
    assert repo.get_subject("per_1").claim_seq == 2
    assert [c.seq for c in repo.list_subject_claims("per_1")] == [1, 2]


def test_list_subject_claims_before_seq(repo):
    repo.ensure_source(SOURCE)
    for seq in range(1, 5):
        repo.publish_claim_tx(plan(seq))
    assert [c.seq for c in repo.list_subject_claims("per_1", before_seq=3)] == [1, 2]
    assert repo.list_subject_claims("per_1", before_seq=1) == []
    assert repo.list_subject_claims("per_other") == []


def test_reused_marker_is_idempotency_conflict(repo):
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan(1))
    with pytest.raises(IdempotencyConflict):
        repo.publish_claim_tx(plan(2, ref="REF-1"))
    assert repo.get_subject("per_1").claim_seq == 1


def test_stale_sequence_is_sequence_conflict(repo):
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan(1))
    repo.publish_claim_tx(plan(2))
    with pytest.raises(SequenceConflict):
        repo.publish_claim_tx(plan(3, expected=1, claim_id="clm_late"))
    assert repo.get_idempotency("org_p", "REF-3") is None


def test_creating_existing_subject_is_sequence_conflict(repo):
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan(1))
    with pytest.raises(SequenceConflict):
        repo.publish_claim_tx(plan(1, ref="REF-other", claim_id="clm_other"))


def test_missing_source_is_rejected(repo):
    with pytest.raises(ValueError):
        repo.publish_claim_tx(plan(1))
    assert repo.get_subject("per_1") is None


def test_ingest_service_end_to_end(service, repo):
    hospital = service.publish(cmd(org=HOSPITAL, ref="CH-1", claim_type="FOUND_SAFE")).claim
    relay = service.publish(
        cmd(
            org=NGO,
            ref="NGO-1",
            subject=person(hospital.subject_id),
            claim_type="FOUND_SAFE",
            original_text="According to Central Hospital Demo, Maya R. was admitted.",
        )
    ).claim
    assert relay.seq == 2
    assert relay.mentioned_source_ids == (hospital.source_id,)
    assert repo.get_claim(relay.id) == relay

    again = service.publish(cmd(org=HOSPITAL, ref="CH-1", claim_type="FOUND_SAFE"))
    assert again.replayed and again.claim.id == hospital.id
    with pytest.raises(ReferenceConflict):
        service.publish(cmd(org=HOSPITAL, ref="CH-1", original_text="Different."))


def test_service_retries_when_another_writer_takes_the_sequence(repo):
    service = IngestService(repo, clock=FixedClock(), sleep=lambda _: None)
    subject_id = service.publish(cmd()).claim.subject_id
    real_tx = repo.publish_claim_tx
    raced = []

    def racing_tx(p):
        if not raced:
            raced.append(True)
            competing = cmd(org=NGO, ref="NGO-1", subject=person(subject_id))
            service.publish(competing)
        return real_tx(p)

    repo.publish_claim_tx = racing_tx
    late = service.publish(cmd(org=HOSPITAL, ref="CH-1", subject=person(subject_id))).claim
    assert late.seq == 3
    assert [c.seq for c in repo.list_subject_claims(subject_id)] == [1, 2, 3]


def publish_people(service, *names):
    ids = {}
    for i, name in enumerate(names):
        new = {"type": "PERSON", "new": {"name": name}}
        ids[name] = service.publish(cmd(ref=f"P-{i}", subject=new)).claim.subject_id
    return ids


def test_list_subjects_pages_by_name(service, repo):
    ids = publish_people(service, "Ravi Kumar", "Maya Rawat", "Asha Devi")
    service.publish(
        cmd(
            ref="S-1",
            subject={"type": "SHELTER", "new": {"name": "Aaa Camp"}},
            claim_type="SHELTER_OPEN",
        )
    )
    first = repo.list_subjects("inc_1", "PERSON", 2)
    assert [s.display_name for s in first] == ["Asha Devi", "Maya Rawat"]
    after = NamePosition(name_norm=first[-1].name_norm, subject_id=first[-1].id)
    rest = repo.list_subjects("inc_1", "PERSON", 2, after)
    assert [s.id for s in rest] == [ids["Ravi Kumar"]]
    assert repo.list_subjects("inc_2", "PERSON", 10) == []


def test_find_subject_ids_by_token_prefix(service, repo):
    ids = publish_people(service, "Maya Rawat", "Mohan Rawat", "Ravi Kumar")
    assert repo.find_subject_ids_by_token("inc_1", "raw") == sorted(
        [ids["Maya Rawat"], ids["Mohan Rawat"]]
    )
    assert repo.find_subject_ids_by_token("inc_1", "ra") == sorted(ids.values())
    assert repo.find_subject_ids_by_token("inc_1", "zz") == []
    assert repo.find_subject_ids_by_token("inc_2", "raw") == []


def test_get_subjects_keeps_order_and_skips_unknown(service, repo):
    ids = publish_people(service, "Maya Rawat", "Ravi Kumar")
    wanted = [ids["Ravi Kumar"], "per_missing", ids["Maya Rawat"], ids["Ravi Kumar"]]
    got = repo.get_subjects(wanted)
    assert [s.display_name for s in got] == ["Ravi Kumar", "Maya Rawat"]
    assert repo.get_subjects([]) == []


def test_get_subjects_batches_past_the_key_limit(service, repo):
    ids = publish_people(
        service, *[f"Person {chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(105)]
    )
    assert len(repo.get_subjects(list(ids.values()))) == 105


def test_get_source_is_scoped_to_incident(repo):
    repo.ensure_source(SOURCE)
    assert repo.get_source("inc_1", "src_police") == SOURCE
    assert repo.get_source("inc_2", "src_police") is None


def test_list_subscriptions_reads_only_the_subjects_followers(repo, table):
    subs = [
        Subscription(id="sub_1", subject_id="per_1", user_id="u1", channel_sms=True),
        Subscription(id="sub_2", subject_id="per_1", user_id="u2", active=False),
        Subscription(id="sub_3", subject_id="per_2", user_id="u3"),
    ]
    for sub in subs:
        table.put_item(Item=subscription_item(sub))
    repo.ensure_source(SOURCE)
    repo.publish_claim_tx(plan())
    assert repo.list_subscriptions("per_1") == subs[:2]
    assert len(repo.list_subject_claims("per_1")) == 1


def alert(alert_id="alr_1", subscription_id="sub_1"):
    return Alert(
        id=alert_id,
        incident_id="inc_1",
        subject_id="per_1",
        subscription_id=subscription_id,
        claim_id="clm_1",
        user_id="u1",
        relation="FIRST",
        severity="info",
        message="First report.",
        delivery_status="PENDING",
        created_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
    )


def test_alert_is_stored_once_per_subscription_and_claim(repo, table):
    assert repo.put_alert_if_absent(alert()) is True
    assert repo.put_alert_if_absent(alert(alert_id="alr_2")) is False
    assert repo.put_alert_if_absent(alert(alert_id="alr_3", subscription_id="sub_2")) is True
    item = table.get_item(Key={"PK": "SUB#sub_1", "SK": "ALR#clm_1"})["Item"]
    assert item["id"] == "alr_1" and item["entity_type"] == "ALERT"
    assert item["GSI1PK"] == "USER#u1"
    assert item["GSI1SK"] == "ALR#2026-10-05T10:15:00Z#alr_1"
    assert item["GSI3PK"] == "ALERT#alr_1"


def test_review_item_is_stored_once_and_queued_by_priority(repo, table):
    item = ReviewItem(
        id="rev_1",
        incident_id="inc_1",
        item_type="conflict",
        ref_id="clm_1",
        subject_id="per_1",
        priority=2,
        created_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
    )
    assert repo.put_review_item_if_absent(item) is True
    assert repo.put_review_item_if_absent(item) is False
    stored = table.get_item(Key={"PK": "INC#inc_1", "SK": "REV#rev_1"})["Item"]
    assert stored["entity_type"] == "REVIEW_ITEM" and stored["status"] == "OPEN"
    assert stored["GSI2PK"] == "REVQ#inc_1#OPEN"
    assert stored["GSI2SK"] == "2#2026-10-05T10:15:00Z#rev_1"


def test_subscription_save_overwrites_and_lists_by_user(repo):
    sub = Subscription(id="sub_1", subject_id="per_1", user_id="u1")
    repo.save_subscription(sub)
    updated = sub.model_copy(update={"channel_email": True, "email": "a@example.org"})
    repo.save_subscription(updated)
    repo.save_subscription(Subscription(id="sub_2", subject_id="per_2", user_id="u2"))
    assert repo.get_subscription("per_1", "sub_1") == updated
    assert repo.get_subscription("per_2", "sub_1") is None
    assert repo.list_user_subscriptions("u1") == [updated]


def test_user_alerts_are_newest_first_with_exact_pages(repo):
    from datetime import timedelta

    base = datetime(2026, 10, 5, tzinfo=UTC)
    for n in range(5):
        repo.put_alert_if_absent(
            alert(alert_id=f"alr_{n}", subscription_id=f"sub_{n}").model_copy(
                update={"created_at": base + timedelta(minutes=n)}
            )
        )
    repo.put_alert_if_absent(
        alert(alert_id="alr_other", subscription_id="sub_x").model_copy(update={"user_id": "u2"})
    )
    page, after = repo.list_user_alerts("u1", 2)
    assert [a.id for a in page] == ["alr_4", "alr_3"]
    page, after = repo.list_user_alerts("u1", 2, after)
    assert [a.id for a in page] == ["alr_2", "alr_1"]
    page, after = repo.list_user_alerts("u1", 2, after)
    assert [a.id for a in page] == ["alr_0"] and after is None
    page, after = repo.list_user_alerts("u1", 5)
    assert len(page) == 5 and after is None


def test_user_alerts_reject_another_users_position(repo):
    for n in range(3):
        repo.put_alert_if_absent(alert(alert_id=f"alr_{n}", subscription_id=f"sub_{n}"))
    _, after = repo.list_user_alerts("u1", 1)
    with pytest.raises(ValueError):
        repo.list_user_alerts("u2", 1, after)


def connection(cid, user="u1", minute=0):
    from datetime import timedelta

    at = datetime(2026, 10, 5, 10, minute, tzinfo=UTC)
    return Connection(
        id=cid,
        user_id=user,
        groups=("reviewer",),
        connected_at=at,
        expires_at=at + timedelta(hours=2),
    )


def test_connections_round_trip_with_ttl_and_lookups(repo, table):
    repo.put_connection(connection("c1"))
    repo.put_connection(connection("c2", minute=1))
    repo.put_connection(connection("c3", user="u2"))
    item = table.get_item(Key={"PK": "CONN#c1", "SK": "META"})["Item"]
    assert item["ttl"] == int(connection("c1").expires_at.timestamp())
    assert "GSI3PK" not in item
    assert repo.get_connection("c1") == connection("c1")
    assert [c.id for c in repo.list_user_connections("u1")] == ["c1", "c2"]

    assert repo.set_connection_incident("c1", "inc_1") is True
    assert repo.get_connection("c1").incident_id == "inc_1"
    assert [c.id for c in repo.list_incident_connections("inc_1")] == ["c1"]
    assert repo.set_connection_incident("c_gone", "inc_1") is False

    repo.delete_connection("c1")
    assert repo.get_connection("c1") is None
    assert repo.list_incident_connections("inc_1") == []


def test_locations_keep_exact_coordinates(repo, table):
    place = Location(
        id="loc_1", incident_id="inc_1", name="Old Bridge", name_norm="old bridge",
        lat=30.7268, lon=78.4354,
    )  # fmt: skip
    named = Location(
        id="loc_2", incident_id="inc_1", name="Upper Village", name_norm="upper village"
    )
    assert repo.ensure_location(place) == place
    assert repo.ensure_location(place.model_copy(update={"name": "Other"})) == place
    repo.ensure_location(named)
    item = table.get_item(Key={"PK": "INC#inc_1", "SK": "LOC#loc_1"})["Item"]
    assert item["entity_type"] == "LOCATION"
    assert sorted(repo.list_locations("inc_1"), key=lambda loc: loc.id) == [place, named]
    assert repo.list_locations("inc_2") == []


def test_list_incident_claims_reads_every_claim_of_the_incident(service, repo):
    first = service.publish(cmd(ref="R1")).claim
    second = service.publish(
        cmd(ref="R2", location={"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354})
    ).claim
    found = repo.list_incident_claims("inc_1")
    assert {c.id for c in found} == {first.id, second.id}
    assert next(c for c in found if c.id == second.id).location_id == second.location_id
    assert repo.list_incident_claims("inc_2") == []


def test_get_review_item_is_scoped_to_incident(repo):
    item = ReviewItem(
        id="rev_9",
        incident_id="inc_1",
        item_type="held_alert",
        ref_id="clm_9",
        priority=1,
        created_at=datetime(2026, 10, 5, 10, 15, tzinfo=UTC),
    )
    repo.put_review_item_if_absent(item)
    assert repo.get_review_item("inc_1", "rev_9") == item
    assert repo.get_review_item("inc_2", "rev_9") is None
    assert repo.get_review_item("inc_1", "rev_x") is None
