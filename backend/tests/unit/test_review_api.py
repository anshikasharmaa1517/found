import pytest

from found_core import container
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import ReviewItemType
from found_core.domain.ids import review_item_id
from found_core.services.review import ReviewService
from found_core.services.watch import WatchService
from tests.unit.test_api_handler import BODY, FixedClock, call, event, publish
from tests.unit.test_api_handler import repo as api_repo  # noqa: F401 - fixture

REVIEWER = {"sub": "rev_1", "cognito:groups": "[reviewer]"}
FAMILY = {"sub": "fam_1", "cognito:groups": "[family]"}


@pytest.fixture
def world(api_repo, monkeypatch):  # noqa: F811
    service = ReviewService(api_repo, CursorCodec(b"k" * 32), clock=FixedClock())
    monkeypatch.setattr(container, "review_service", lambda: service)
    watch = WatchService(api_repo, clock=FixedClock())
    _, body, _ = publish({**BODY, "claim_type": "DECEASED"})
    claim = api_repo.get_claim(body["claim"]["id"])
    watch.on_claim_created(claim.subject_id, claim.id, claim.seq)
    return api_repo, claim


def test_queue_shows_the_held_report_to_reviewers(world):
    _, claim = world
    status, body, _ = call(event("GET", "/v1/incidents/inc_1/review-queue", claims=REVIEWER))
    assert status == 200 and body["next_cursor"] is None
    (item,) = body["items"]
    assert item["type"] == "held_alert" and item["status"] == "OPEN" and item["priority"] == 1
    assert item["claim"]["id"] == claim.id and item["claim"]["claim_type"] == "DECEASED"
    assert item["claim"]["source"] == "Central Hospital Demo"
    assert item["person"]["name"] == "Maya Rawat"
    assert item["investigation"] is None


def test_queue_refuses_families_and_bad_filters(world):
    path = "/v1/incidents/inc_1/review-queue"
    assert call(event("GET", path, claims=FAMILY))[0] == 403
    assert call(event("GET", path, claims=REVIEWER, query={"type": "x"}))[0] == 400


def test_release_closes_the_item(world):
    _, claim = world
    rid = review_item_id(ReviewItemType.HELD_ALERT, claim.id)
    path = f"/v1/incidents/inc_1/review-items/{rid}/resolve"
    status, body, _ = call(event("POST", path, {"note": "Family told."}, REVIEWER))
    assert status == 200
    assert body == {"id": rid, "status": "DONE", "resolved_by": "rev_1", "alerts_released": 0}
    assert call(event("POST", path, None, REVIEWER))[0] == 409


def test_investigation_review_needs_a_finding(world):
    path = "/v1/investigations/inv_x/review"
    assert call(event("POST", path, {"decision": "ACCEPTED"}, REVIEWER))[0] == 404
    assert call(event("POST", path, {"decision": "NOPE"}, REVIEWER))[0] == 400
