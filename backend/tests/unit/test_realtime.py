import json
from datetime import UTC, datetime, timedelta

import pytest

from found_core.adapters.memory import InMemoryFoundRepository
from found_core.domain.auth import Caller
from found_core.domain.errors import BadRequest, Forbidden, NotFound
from found_core.domain.models import Connection, Organization
from found_core.events import (
    AlertCreated,
    ClaimCreated,
    InvestigationStepCreated,
    InvestigationUpdated,
    ReviewCreated,
    SubjectCreated,
)
from found_core.realtime import message_for, receives
from found_core.services.realtime import ConnectionService, PushService

NOW = datetime(2026, 10, 5, 10, 15, tzinfo=UTC)


class FixedClock:
    def __init__(self) -> None:
        self.at = NOW

    def now(self):
        return self.at


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.closed: list[str] = []
        self.gone: set[str] = set()
        self.broken: set[str] = set()

    def send(self, connection_id, data):
        if connection_id in self.broken:
            raise RuntimeError("network")
        if connection_id in self.gone:
            return False
        self.sent.append((connection_id, json.loads(data)))
        return True

    def close(self, connection_id):
        self.closed.append(connection_id)


CLAIM = ClaimCreated(
    event_id="e1",
    incident_id="inc_1",
    subject_id="per_1",
    subject_type="PERSON",
    claim_id="clm_1",
    seq=2,
    source_id="src_1",
    occurred_at=NOW,
)
ALERT = AlertCreated(
    event_id="e2",
    incident_id="inc_1",
    alert_id="alr_1",
    user_id="fam_1",
    subject_id="per_1",
    claim_id="clm_1",
    severity="info",
    message="Newer report for Maya Rawat.",
    occurred_at=NOW,
)
REVIEW = ReviewCreated(
    event_id="e3",
    incident_id="inc_1",
    review_id="rev_1",
    item_type="conflict",
    ref_id="clm_1",
    priority=2,
    occurred_at=NOW,
)


def conn(cid, user="u", groups=("reviewer",), incident="inc_1", minutes=0, org=None):
    return Connection(
        id=cid,
        user_id=user,
        groups=groups,
        org_id=org,
        incident_id=incident,
        connected_at=NOW + timedelta(minutes=minutes),
        expires_at=NOW + timedelta(hours=2, minutes=minutes),
    )


def test_messages_match_the_protocol():
    assert message_for(CLAIM) == {
        "type": "claim.created",
        "incident_id": "inc_1",
        "claim_id": "clm_1",
        "subject_id": "per_1",
        "at": "2026-10-05T10:15:00Z",
    }
    assert message_for(ALERT) == {
        "type": "alert.created",
        "alert_id": "alr_1",
        "subject_id": "per_1",
        "severity": "info",
        "message": "Newer report for Maya Rawat.",
    }
    assert message_for(REVIEW) == {
        "type": "review.created",
        "incident_id": "inc_1",
        "review_id": "rev_1",
        "item_type": "conflict",
    }


def test_subject_events_are_not_pushed():
    event = SubjectCreated(
        event_id="e", incident_id="inc_1", subject_id="per_1", subject_type="PERSON",
        occurred_at=NOW,
    )  # fmt: skip
    assert message_for(event) is None


@pytest.mark.parametrize(
    ("connection", "event", "expected"),
    [
        (conn("c", groups=("reviewer",)), CLAIM, True),
        (conn("c", groups=("publisher",)), CLAIM, True),
        (conn("c", groups=("family",)), CLAIM, False),
        (conn("c", groups=("reviewer",), incident="inc_2"), CLAIM, False),
        (conn("c", groups=("reviewer",), incident=None), CLAIM, False),
        (conn("c", groups=("reviewer",)), REVIEW, True),
        (conn("c", groups=("publisher",)), REVIEW, False),
        (conn("c", groups=("family",)), REVIEW, False),
        (conn("c", user="fam_1", groups=("family",), incident=None), ALERT, True),
        (conn("c", user="fam_2", groups=("family",)), ALERT, False),
        (conn("c", user="rev", groups=("reviewer",)), ALERT, False),
    ],
)
def test_audience(connection, event, expected):
    assert receives(connection, event) is expected


@pytest.fixture
def repo():
    r = InMemoryFoundRepository()
    r.add_incident("inc_1")
    r.add_incident("inc_2")
    r.add_organization(
        Organization(
            id="org_h", incident_id="inc_1", name="Hospital", name_norm="hospital",
            org_type="HOSPITAL",
        )
    )  # fmt: skip
    return r


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def connections(repo, gateway, clock):
    return ConnectionService(repo, gateway, clock=clock)


REVIEWER = Caller(user_id="rev_1", groups=frozenset({"reviewer"}))
PUBLISHER = Caller(user_id="pub_1", groups=frozenset({"publisher"}), org_id="org_h")


def test_connect_stores_identity_with_two_hour_expiry(connections, repo):
    stored = connections.connect(PUBLISHER, "c1")
    assert repo.get_connection("c1") == stored
    assert stored.groups == ("publisher",) and stored.org_id == "org_h"
    assert stored.expires_at - stored.connected_at == timedelta(hours=2)
    assert stored.incident_id is None


def test_fourth_connection_evicts_the_oldest(connections, repo, gateway, clock):
    for n in range(4):
        clock.at = NOW + timedelta(minutes=n)
        connections.connect(REVIEWER, f"c{n}")
    assert sorted(repo.connections) == ["c1", "c2", "c3"]
    assert gateway.closed == ["c0"]


def test_expired_connections_do_not_count(connections, repo, gateway, clock):
    repo.put_connection(conn("old", user="rev_1", minutes=-180))
    connections.connect(REVIEWER, "c1")
    connections.connect(REVIEWER, "c2")
    assert gateway.closed == []


def test_disconnect_removes_the_connection(connections, repo):
    connections.connect(REVIEWER, "c1")
    connections.disconnect("c1")
    connections.disconnect("c1")
    assert repo.connections == {}


def test_subscribe_points_the_connection_at_an_incident(connections, repo):
    connections.connect(REVIEWER, "c1")
    assert connections.subscribe("c1", {"incident_id": "inc_1"}) == "inc_1"
    assert connections.subscribe("c1", {"incident_id": "inc_2"}) == "inc_2"
    assert repo.get_connection("c1").incident_id == "inc_2"


@pytest.mark.parametrize(
    "body", [{}, {"incident_id": ""}, {"incident_id": 5}, {"incident_id": "x" * 65}]
)
def test_subscribe_needs_an_incident_id(connections, body):
    connections.connect(REVIEWER, "c1")
    with pytest.raises(BadRequest):
        connections.subscribe("c1", body)


def test_subscribe_checks_incident_and_access(connections):
    connections.connect(PUBLISHER, "c1")
    with pytest.raises(NotFound):
        connections.subscribe("c1", {"incident_id": "inc_missing"})
    with pytest.raises(Forbidden):
        connections.subscribe("c1", {"incident_id": "inc_2"})
    with pytest.raises(NotFound):
        connections.subscribe("c_unknown", {"incident_id": "inc_1"})


@pytest.fixture
def push(repo, gateway, clock):
    return PushService(repo, gateway, clock=clock)


def test_claim_goes_to_staff_watching_the_incident(push, repo, gateway):
    repo.put_connection(conn("staff"))
    repo.put_connection(conn("fam", groups=("family",)))
    repo.put_connection(conn("other", incident="inc_2"))
    result = push.push(CLAIM)
    assert result.sent == 1
    assert gateway.sent == [("staff", message_for(CLAIM))]


def test_alert_goes_to_every_tab_of_its_user_only(push, repo, gateway):
    repo.put_connection(conn("tab1", user="fam_1", groups=("family",), incident=None))
    repo.put_connection(conn("tab2", user="fam_1", groups=("family",), incident="inc_2"))
    repo.put_connection(conn("someone", user="fam_2", groups=("family",)))
    push.push(ALERT)
    assert sorted(cid for cid, _ in gateway.sent) == ["tab1", "tab2"]


def test_gone_connections_are_cleaned_and_broken_ones_do_not_stop_others(push, repo, gateway):
    for cid in ("a", "b", "c"):
        repo.put_connection(conn(cid))
    gateway.gone = {"a"}
    gateway.broken = {"b"}
    result = push.push(CLAIM)
    assert (result.sent, result.gone, result.failed) == (1, 1, 1)
    assert "a" not in repo.connections and "b" in repo.connections
    assert [cid for cid, _ in gateway.sent] == ["c"]


def test_expired_connections_are_skipped(push, repo, gateway, clock):
    repo.put_connection(conn("stale"))
    clock.at = NOW + timedelta(hours=3)
    assert push.push(CLAIM).sent == 0 and gateway.sent == []


def test_nothing_to_push_is_a_no_op(push, gateway):
    assert push.push(CLAIM).sent == 0 and gateway.sent == []


STEP = InvestigationStepCreated(
    event_id="e4",
    incident_id="inc_1",
    investigation_id="inv_1",
    seq=3,
    kind="TOOL",
    tool_name="find_reports_by_source",
    summary="2 reports from Central Hospital Demo",
    occurred_at=NOW,
)
UPDATED = InvestigationUpdated(
    event_id="e5",
    incident_id="inc_1",
    investigation_id="inv_1",
    claim_id="clm_1",
    status="NEEDS_REVIEW",
    occurred_at=NOW,
)


def test_investigation_messages_match_the_protocol():
    assert message_for(STEP) == {
        "type": "investigation.step",
        "incident_id": "inc_1",
        "investigation_id": "inv_1",
        "seq": 3,
        "kind": "TOOL",
        "tool": "find_reports_by_source",
        "summary": "2 reports from Central Hospital Demo",
    }
    assert message_for(UPDATED) == {
        "type": "investigation.updated",
        "incident_id": "inc_1",
        "investigation_id": "inv_1",
        "claim_id": "clm_1",
        "status": "NEEDS_REVIEW",
    }


@pytest.mark.parametrize("event", [STEP, UPDATED])
@pytest.mark.parametrize(
    ("groups", "incident", "expected"),
    [
        (("reviewer",), "inc_1", True),
        (("admin",), "inc_1", True),
        (("reviewer",), "inc_2", False),
        (("publisher",), "inc_1", False),
        (("family",), "inc_1", False),
    ],
)
def test_investigations_go_to_reviewers_of_the_incident(event, groups, incident, expected):
    assert receives(conn("c", groups=groups, incident=incident), event) is expected
