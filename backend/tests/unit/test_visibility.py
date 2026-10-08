import json
from datetime import UTC, datetime

import pytest

from found_core import container
from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.commands import PublishCommand
from found_core.domain.cursor import CursorCodec
from found_core.domain.enums import ReviewItemType, ReviewStatus
from found_core.domain.ids import review_item_id
from found_core.domain.models import Organization
from found_core.domain.rules import summarize
from found_core.domain.visibility import (
    SENSITIVE_BASIS,
    SENSITIVE_LABEL,
    SENSITIVE_NOTICE,
    masked_summary,
    withheld_ids,
)
from found_core.services.ingest import IngestService
from found_core.services.people import PeopleService
from found_core.services.watch import WatchService
from handlers import api

from .factories import claim

T1 = "2026-10-02T15:40:00+00:00"
T2 = "2026-10-03T02:10:00+00:00"

REVIEWER = Caller(user_id="rev", groups=frozenset({"reviewer"}))
ADMIN = Caller(user_id="adm", groups=frozenset({"admin"}))
FAMILY = Caller(user_id="fam", groups=frozenset({"family"}))
PUBLISHER = Caller(user_id="pub", groups=frozenset({"publisher"}), org_id="org_h")


def test_only_reviewers_and_admins_see_unreleased_sensitive_claims():
    claims = [claim(1, "MISSING", T1), claim(2, "DECEASED", T2)]
    assert withheld_ids(claims, REVIEWER, set()) == frozenset()
    assert withheld_ids(claims, ADMIN, set()) == frozenset()
    assert withheld_ids(claims, FAMILY, set()) == {"clm_2"}
    assert withheld_ids(claims, PUBLISHER, set()) == {"clm_2"}
    assert withheld_ids(claims, FAMILY, {"clm_2"}) == frozenset()


def test_summary_citing_a_withheld_claim_still_cites_it_but_says_nothing():
    claims = [claim(1, "MISSING", T1), claim(2, "DECEASED", T2)]
    summary = masked_summary(summarize(claims, "PERSON"), {"clm_2"})
    assert summary.cited_claim_id == "clm_2"
    assert summary.label == SENSITIVE_LABEL and summary.basis == SENSITIVE_BASIS
    assert "deceased" not in f"{summary.label} {summary.basis}".lower()


def test_summary_of_a_visible_claim_is_unchanged():
    summary = summarize([claim(1, "MISSING", T1)], "PERSON")
    assert masked_summary(summary, {"clm_9"}) is summary


class FixedClock:
    def now(self):
        return datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


POLICE = {"org_id": "org_p", "org_name": "District Police Demo", "org_type": "POLICE"}
MORGUE = {"org_id": "org_m", "org_name": "District Morgue Demo", "org_type": "HOSPITAL"}


class World:
    def __init__(self) -> None:
        self.repo = InMemoryFoundRepository()
        self.repo.add_incident("inc_1")
        self.repo.add_organization(
            Organization(
                id="org_h", incident_id="inc_1", name="Hospital", name_norm="hospital",
                org_type="HOSPITAL",
            )
        )  # fmt: skip
        self.ingest = IngestService(self.repo, clock=FixedClock(), sleep=lambda _: None)
        self.watch = WatchService(self.repo, clock=FixedClock())
        self.people = PeopleService(self.repo, CursorCodec(b"k" * 32))
        self.refs = 0
        self.person_id = self.report(POLICE, "MISSING", "2026-10-02T21:10:00+05:30", new=True)
        self.report(MORGUE, "DECEASED", "2026-10-03T07:40:00+05:30")

    def report(self, org, claim_type, reported_at, new=False):
        self.refs += 1
        subject = (
            {"type": "PERSON", "new": {"name": "Maya Rawat"}}
            if new
            else {"type": "PERSON", "id": self.person_id}
        )
        stored = self.ingest.publish(
            PublishCommand.parse(
                {
                    "incident_id": "inc_1",
                    **org,
                    "actor": "pub",
                    "subject": subject,
                    "claim_type": claim_type,
                    "value": "Body identified by family" if claim_type == "DECEASED" else None,
                    "original_text": (
                        "Identified at the district morgue."
                        if claim_type == "DECEASED"
                        else "Missing since the bridge collapse."
                    ),
                    "external_reference": f"REF-{self.refs}",
                    "reported_at": reported_at,
                }
            )
        ).claim
        self.watch.on_claim_created(stored.subject_id, stored.id, stored.seq)
        return stored.subject_id

    def release(self):
        deceased = self.repo.list_subject_claims(self.person_id)[1]
        review_id = review_item_id(ReviewItemType.HELD_ALERT, deceased.id)
        item = self.repo.review_items[review_id]
        self.repo.review_items[review_id] = item.model_copy(update={"status": ReviewStatus.DONE})


@pytest.fixture
def world():
    return World()


def test_watcher_holds_every_sensitive_claim_even_without_followers(world):
    deceased = world.repo.list_subject_claims(world.person_id)[1]
    item = world.repo.review_items[review_item_id(ReviewItemType.HELD_ALERT, deceased.id)]
    assert item.status == ReviewStatus.OPEN and item.priority == 1


@pytest.mark.parametrize("caller", [FAMILY, PUBLISHER])
def test_others_see_a_neutral_entry_until_released(world, caller):
    timeline = world.people.timeline(caller, world.person_id)
    withheld = [e for e in timeline.entries if e.withheld]
    assert len(withheld) == 1
    assert timeline.profile.summary.label == SENSITIVE_LABEL

    world.release()
    released = world.people.timeline(caller, world.person_id)
    assert not any(e.withheld for e in released.entries)
    assert released.profile.summary.label == "Reported deceased"


@pytest.mark.parametrize("caller", [REVIEWER, ADMIN])
def test_reviewers_and_admins_see_everything(world, caller):
    timeline = world.people.timeline(caller, world.person_id)
    assert not any(e.withheld for e in timeline.entries)
    assert timeline.profile.summary.label == "Reported deceased"


def test_withheld_conflict_is_masked_too(world):
    # A later missing report makes the deceased one a conflict instead of the cited claim.
    world.report(POLICE, "MISSING", "2026-10-04T09:00:00+05:30")
    profile = world.people.profile(FAMILY, world.person_id)
    assert profile.summary.label == "Reported missing"
    assert [c.claim_type for c in profile.conflicts] == ["DECEASED"]
    assert profile.conflicts[0].id in profile.withheld


class Context:
    function_name = "api"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:ap-south-1:111111111111:function:api"
    aws_request_id = "req-1"


def get(path, claims):
    event = {
        "version": "2.0",
        "routeKey": f"GET {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {"method": "GET", "path": path, "protocol": "HTTP/1.1", "sourceIp": "1.1.1.1"},
            "requestId": "req-abc",
            "routeKey": f"GET {path}",
            "stage": "$default",
            "authorizer": {"jwt": {"claims": claims, "scopes": None}},
        },
        "isBase64Encoded": False,
    }
    response = api.handler(event, Context())
    return response["statusCode"], response["body"]


def test_api_response_leaves_out_type_text_and_source_for_families(world, monkeypatch):
    monkeypatch.setattr(container, "people_service", lambda: world.people)
    family = {"sub": "fam", "cognito:groups": "[family]"}
    status, raw = get(f"/v1/people/{world.person_id}/timeline", family)
    assert status == 200
    for word in ("DECEASED", "Deceased", "deceased", "morgue", "Morgue", "Body identified"):
        assert word not in raw
    body = json.loads(raw)
    withheld = next(e for e in body["entries"] if e["withheld"])
    assert set(withheld) == {"claim_id", "seq", "reported_at", "withheld", "notice"}
    assert withheld["notice"] == SENSITIVE_NOTICE
    assert body["summary"]["cited_claim_id"] == withheld["claim_id"]

    reviewer = {"sub": "rev", "cognito:groups": "[reviewer]"}
    _, raw = get(f"/v1/people/{world.person_id}/timeline", reviewer)
    assert "DECEASED" in raw and "District Morgue Demo" in raw


def test_api_masks_withheld_conflicts(world, monkeypatch):
    world.report(POLICE, "MISSING", "2026-10-04T09:00:00+05:30")
    monkeypatch.setattr(container, "people_service", lambda: world.people)
    _, raw = get(f"/v1/people/{world.person_id}", {"sub": "fam", "cognito:groups": "[family]"})
    conflicts = json.loads(raw)["summary"]["conflicts"]
    assert conflicts == [
        {"claim_id": conflicts[0]["claim_id"], "withheld": True, "notice": SENSITIVE_NOTICE}
    ]
    assert "DECEASED" not in raw and "Morgue" not in raw
