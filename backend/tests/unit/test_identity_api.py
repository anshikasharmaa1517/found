from urllib.parse import quote

import pytest

from found_core import container
from found_core.domain.cursor import CursorCodec
from found_core.domain.identity import pair_key
from found_core.services.resolve import ResolveService
from found_core.services.review import ReviewService
from tests.unit.test_api_handler import BODY, FixedClock, call, event, publish
from tests.unit.test_api_handler import repo as api_repo  # noqa: F401 - fixture

REVIEWER = {"sub": "rev_1", "cognito:groups": "[reviewer]"}
FAMILY = {"sub": "fam_1", "cognito:groups": "[family]"}
PLACE = {"name": "Old Bridge", "lat": 30.7268, "lon": 78.4354}


@pytest.fixture
def pair(api_repo, monkeypatch):  # noqa: F811
    resolver = ResolveService(api_repo, clock=FixedClock())
    monkeypatch.setattr(container, "resolve_service", lambda: resolver)
    review = ReviewService(api_repo, CursorCodec(b"k" * 32), clock=FixedClock())
    monkeypatch.setattr(container, "review_service", lambda: review)
    ids = []
    for ref, name in (("CH-1", "Maya Rawat"), ("CH-2", "Maya R.")):
        body = {
            **BODY,
            "subject": {"type": "PERSON", "new": {"name": name, "age": 24}},
            "external_reference": ref,
            "location": PLACE,
        }
        status, created, _ = publish(body)
        assert status == 201
        ids.append(created["claim"]["subject_id"])
        resolver.on_person_created(ids[-1])
    return ids, pair_key(*ids)


def decision_path(key, encode=True):
    return f"/v1/identity-proposals/{quote(key, safe='') if encode else key}/decision"


DECIDE = {"decision": "CONFIRMED", "note": "Same age, same bridge.", "expected_version": 0}


def test_the_queue_shows_the_pair_with_its_reasons(pair):
    ids, key = pair
    status, body, _ = call(
        event(
            "GET", "/v1/incidents/inc_1/review-queue", claims=REVIEWER, query={"type": "identity"}
        )
    )
    assert status == 200
    (item,) = body["items"]
    assert item["type"] == "identity" and item["ref_id"] == key and item["claim"] is None
    proposal = item["proposal"]
    assert proposal["pair_key"] == key and proposal["score"] == 55
    assert proposal["reasons"] == ["GIVEN_EXACT", "AGE_EQUAL", "SHARED_LOCATION"]
    assert [p["id"] for p in proposal["people"]] == sorted(ids)
    assert {p["name"] for p in proposal["people"]} == {"Maya Rawat", "Maya R."}


@pytest.mark.parametrize("encode", [True, False])
def test_a_reviewer_decides_and_both_pages_show_it(pair, encode):
    ids, key = pair
    status, body, _ = call(event("POST", decision_path(key, encode), DECIDE, REVIEWER))
    assert status == 200
    decision = body["decision"]
    assert decision["pair_key"] == key and decision["decision"] == "CONFIRMED"
    assert decision["version"] == 1 and decision["history"] == []
    assert decision["reviewer"] == "rev_1" and decision["note"] == "Same age, same bridge."

    for me, other in (ids, ids[::-1]):
        status, page, _ = call(event("GET", f"/v1/people/{me}/timeline", claims=FAMILY))
        assert status == 200
        assert page["identity"] == [
            {
                "pair_key": key,
                "other_person_id": other,
                "decision": "CONFIRMED",
                "reviewer": "rev_1",
                "decided_at": "2026-10-05T10:15:00Z",
            }
        ]
        assert len(page["entries"]) == 1
    _, profile, _ = call(event("GET", f"/v1/people/{ids[0]}", claims=FAMILY))
    assert profile["identity"][0]["pair_key"] == key


def test_a_second_decision_needs_the_current_version_and_keeps_history(pair):
    _, key = pair
    path = decision_path(key)
    assert call(event("POST", path, DECIDE, REVIEWER))[0] == 200
    status, body, _ = call(event("POST", path, {**DECIDE, "decision": "REJECTED"}, REVIEWER))
    assert status == 409 and body["error"]["code"] == "VERSION_CONFLICT"
    status, body, _ = call(
        event("POST", path, {**DECIDE, "decision": "REJECTED", "expected_version": 1}, REVIEWER)
    )
    assert status == 200 and body["decision"]["version"] == 2
    assert [h["decision"] for h in body["decision"]["history"]] == ["CONFIRMED"]


def test_errors_map_to_their_statuses(pair):
    ids, key = pair
    path = decision_path(key)
    assert call(event("POST", path, DECIDE, FAMILY))[0] == 403
    assert call(event("POST", path, {**DECIDE, "decision": "MERGE"}, REVIEWER))[0] == 400
    bad_evidence = {**DECIDE, "evidence_claim_ids": ["clm_nope"]}
    assert call(event("POST", path, bad_evidence, REVIEWER))[0] == 422
    assert call(event("POST", decision_path("per_0|per_1"), DECIDE, REVIEWER))[0] == 404
    low, high = sorted(ids)
    assert call(event("POST", decision_path(f"{high}|{low}"), DECIDE, REVIEWER))[0] == 400
