from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.dynamodb import DynamoBudgetLedger
from found_core.domain.commands import PublishCommand
from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.models import Citation, Investigation, Settings
from found_core.services.ingest import IngestService

AT = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)

# Atomicity of the conditional writes is DynamoDB's guarantee and moto does not model it
# across threads, so these tests check each condition in sequence. Parallel behavior is
# covered against the in-memory adapter, which applies conditions under a lock.


class FixedClock:
    def now(self):
        return AT


def investigation(inv_id="inv_1", status=S.QUEUED, **overrides) -> Investigation:
    data = {
        "id": inv_id,
        "incident_id": "inc_1",
        "claim_id": "clm_1",
        "fingerprint": "fp_abc",
        "mode": "LIVE",
        "status": status,
        "model_id": "model-a",
        "prompt_version": "lineage-v1",
        "agent_version": "0.1.0",
        "created_by": "rev_1",
        "queued_at": AT,
        **overrides,
    }
    return Investigation.model_validate(data)


@pytest.fixture
def ledger(table):
    return DynamoBudgetLedger(table)


def test_investigation_round_trips_with_its_index_keys(repo, table):
    inv = investigation()
    repo.put_investigation(inv)
    assert repo.get_investigation("inv_1") == inv
    item = table.get_item(Key={"PK": "INV#inv_1", "SK": "META"})["Item"]
    assert item["entity_type"] == "INVESTIGATION"
    assert item["GSI1PK"] == "INC#inc_1#INV"
    assert item["GSI2PK"] == "CLMINV#clm_1"
    assert item["GSI2SK"] == "2026-10-05T10:15:00Z#inv_1"
    assert "GSI3PK" not in item
    with pytest.raises(ValueError):
        repo.put_investigation(inv)
    assert repo.get_investigation("inv_x") is None


def test_update_is_conditional_on_status(repo):
    repo.put_investigation(investigation())
    running = repo.update_investigation_if("inv_1", S.QUEUED, {"status": S.RUNNING})
    assert running.status == S.RUNNING
    assert repo.update_investigation_if("inv_1", S.QUEUED, {"status": S.FAILED}) is None
    assert repo.update_investigation_if("inv_x", S.QUEUED, {"status": S.RUNNING}) is None
    assert repo.get_investigation("inv_1").status == S.RUNNING


def test_cacheable_result_joins_the_fingerprint_index_and_failure_does_not(repo, table):
    repo.put_investigation(investigation("inv_1", S.RUNNING))
    repo.put_investigation(investigation("inv_2", S.RUNNING))
    repo.update_investigation_if(
        "inv_1", S.RUNNING, {"status": S.FAILED, "failure_reason": "TIMEOUT", "finished_at": AT}
    )
    assert repo.find_cached_investigation("fp_abc") is None
    done = repo.update_investigation_if(
        "inv_2",
        S.RUNNING,
        {
            "status": S.NEEDS_REVIEW,
            "attribution": "RELAY",
            "comparison": "SUPPORTS",
            "citations": [Citation(claim_id="clm_1", excerpt="According to the hospital")],
            "outcome_reasons": ["RELAY_NOT_FIRST_HAND"],
            "finished_at": AT + timedelta(seconds=20),
        },
    )
    assert done.citations[0].excerpt == "According to the hospital"
    item = table.get_item(Key={"PK": "INV#inv_2", "SK": "META"})["Item"]
    assert (item["GSI3PK"], item["GSI3SK"]) == ("FP#fp_abc", "2026-10-05T10:15:20Z")
    assert repo.find_cached_investigation("fp_abc") == done
    assert repo.find_cached_investigation("fp_other") is None


def test_newest_cached_result_wins(repo):
    for n, seconds in ((1, 10), (2, 30), (3, 20)):
        repo.put_investigation(investigation(f"inv_{n}", S.RUNNING))
        repo.update_investigation_if(
            f"inv_{n}",
            S.RUNNING,
            {"status": S.COMPLETED, "finished_at": AT + timedelta(seconds=seconds)},
        )
    assert repo.find_cached_investigation("fp_abc").id == "inv_2"


def test_update_keeps_counters_it_does_not_name(repo, table):
    repo.put_investigation(investigation("inv_1", S.RUNNING))
    # A tool call counted by another writer between this read and write.
    table.update_item(
        Key={"PK": "INV#inv_1", "SK": "META"},
        UpdateExpression="SET tool_calls = :n",
        ExpressionAttributeValues={":n": 3},
    )
    done = repo.update_investigation_if(
        "inv_1", S.RUNNING, {"status": S.FAILED, "summary": None, "finished_at": AT}
    )
    assert done.tool_calls == 3


def test_none_removes_the_attribute(repo, table):
    repo.put_investigation(investigation("inv_1", S.RUNNING, summary="draft"))
    repo.update_investigation_if("inv_1", S.RUNNING, {"summary": None})
    item = table.get_item(Key={"PK": "INV#inv_1", "SK": "META"})["Item"]
    assert "summary" not in item


def test_run_lock_is_exclusive_until_released_or_expired(repo):
    later = AT + timedelta(minutes=10)
    assert repo.acquire_run_lock("clm_1", "inv_1", AT, later) == "inv_1"
    assert repo.acquire_run_lock("clm_1", "inv_2", AT, later) == "inv_1"
    assert repo.acquire_run_lock("clm_2", "inv_3", AT, later) == "inv_3"
    repo.release_run_lock("clm_1", "inv_2")  # not the holder: no effect
    assert repo.acquire_run_lock("clm_1", "inv_4", AT, later) == "inv_1"
    repo.release_run_lock("clm_1", "inv_1")
    assert repo.acquire_run_lock("clm_1", "inv_5", AT, later) == "inv_5"
    # Expired but not yet removed by TTL: taken over.
    assert repo.acquire_run_lock("clm_1", "inv_6", later, later + timedelta(minutes=10)) == "inv_6"


def test_settings_default_to_live_off(repo, table):
    assert repo.get_settings() == Settings()
    table.put_item(
        Item={"PK": "SETTINGS", "SK": "META", "entity_type": "SETTINGS", "live_enabled": True,
              "run_cap": 50}
    )  # fmt: skip
    assert repo.get_settings() == Settings(live_enabled=True, run_cap=50)


def test_latest_source_claim_follows_reported_time(repo):
    service = IngestService(repo, clock=FixedClock(), sleep=lambda _: None)
    hospital = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}

    def publish(ref, reported_at, subject):
        return service.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **hospital,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": "FOUND_SAFE",
                    "original_text": f"Report {ref}.",
                    "external_reference": ref,
                    "reported_at": reported_at,
                }
            )
        ).claim

    first = publish("R1", "2026-10-05T08:00:00Z", {"type": "PERSON", "new": {"name": "Maya"}})
    person = {"type": "PERSON", "id": first.subject_id}
    newest = publish("R2", "2026-10-05T09:00:00Z", person)
    publish("R3", "2026-10-05T07:00:00Z", person)
    assert repo.latest_source_claim_id(first.source_id) == newest.id
    assert repo.latest_source_claim_id("src_none") is None


def test_budget_counts_up_to_the_cap_and_never_past_it(ledger):
    assert ledger.reserve_run("2026-10", 2)
    assert ledger.reserve_run("2026-10", 2)
    assert not ledger.reserve_run("2026-10", 2)
    assert ledger.reserve_run("2026-11", 2)
    assert ledger.count_model_call("2026-10", 1)
    assert not ledger.count_model_call("2026-10", 1)
    ledger.add_tokens("2026-10", 600, 40)
    ledger.add_tokens("2026-10", 100, 10)
    usage = ledger.usage("2026-10")
    assert (usage.runs, usage.model_calls) == (2, 1)
    assert (usage.input_tokens, usage.output_tokens) == (700, 50)
    assert ledger.usage("2026-12").runs == 0


def test_tool_calls_count_only_while_running_and_under_the_cap(repo):
    repo.put_investigation(investigation("inv_1", S.QUEUED))
    assert repo.count_tool_call("inv_1", 2) is None
    repo.update_investigation_if("inv_1", S.QUEUED, {"status": S.RUNNING})
    assert repo.count_tool_call("inv_1", 2) == 1
    assert repo.count_tool_call("inv_1", 2) == 2
    assert repo.count_tool_call("inv_1", 2) is None
    assert repo.count_tool_call("inv_x", 2) is None
    assert repo.get_investigation("inv_1").tool_calls == 2


def test_list_source_claims_newest_first_with_subject_filter(repo):
    service = IngestService(repo, clock=FixedClock(), sleep=lambda _: None)
    hospital = {"org_id": "org_h", "org_name": "Central Hospital Demo", "org_type": "HOSPITAL"}

    def publish(ref, hour, subject):
        return service.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **hospital,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": "FOUND_SAFE",
                    "original_text": f"Report {ref}.",
                    "external_reference": ref,
                    "reported_at": f"2026-10-05T0{hour}:00:00Z",
                }
            )
        ).claim

    maya = publish("R1", 1, {"type": "PERSON", "new": {"name": "Maya"}})
    ravi = publish("R2", 2, {"type": "PERSON", "new": {"name": "Ravi"}})
    maya_later = publish("R3", 3, {"type": "PERSON", "id": maya.subject_id})
    source = maya.source_id
    assert [c.id for c in repo.list_source_claims(source, 10)] == [maya_later.id, ravi.id, maya.id]
    assert [c.id for c in repo.list_source_claims(source, 2)] == [maya_later.id, ravi.id]
    only_maya = repo.list_source_claims(source, 10, subject_id=maya.subject_id)
    assert [c.id for c in only_maya] == [maya_later.id, maya.id]
    # The filter runs after the page limit, so the reader keeps paging to fill it.
    assert [c.id for c in repo.list_source_claims(source, 1, subject_id=ravi.subject_id)] == [
        ravi.id
    ]
