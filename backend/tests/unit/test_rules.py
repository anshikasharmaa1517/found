import pytest

from found_core.domain.enums import DeliveryStatus, Relation, Severity
from found_core.domain.rules import (
    alert_message,
    classify,
    decide_alert,
    delivery_for,
    summarize,
)

from .factories import claim, subscription

T1 = "2026-10-02T15:40:00+00:00"
T2 = "2026-10-03T02:10:00+00:00"


def test_first_status_claim_is_first_and_alerts():
    c = claim(1, "MISSING", T1)
    assert classify(c, []) == Relation.FIRST
    assert decide_alert(c, [], Relation.FIRST).alert


def test_non_status_claim_never_alerts():
    c = claim(2, "SEEN_AT_LOCATION", T2)
    assert classify(c, [claim(1, "MISSING", T1)]) == Relation.NOT_STATUS


@pytest.mark.parametrize(
    ("prior_time", "incoming_time", "expected"),
    [
        (T1, T2, Relation.UPDATE),
        (T2, T1, Relation.HISTORICAL),
        (T1, T1, Relation.NEEDS_REVIEW),
        (None, T2, Relation.NEEDS_REVIEW),
        (T1, None, Relation.NEEDS_REVIEW),
    ],
)
def test_relation_follows_reported_time(prior_time, incoming_time, expected):
    priors = [claim(1, "MISSING", prior_time)]
    incoming = claim(2, "FOUND_SAFE", incoming_time, source_id="src_hospital")
    assert classify(incoming, priors) == expected


def test_newer_different_status_alerts_once_with_kind():
    priors = [claim(1, "MISSING", T1)]
    incoming = claim(2, "FOUND_SAFE", T2, source_id="src_hospital")
    decision = decide_alert(incoming, priors, classify(incoming, priors))
    assert decision.alert and decision.kind == "Newer report"
    assert decision.severity == Severity.INFO


def test_late_arriving_earlier_report_is_labeled_historical():
    priors = [claim(1, "FOUND_SAFE", T2, source_id="src_hospital")]
    incoming = claim(2, "MISSING", T1)
    decision = decide_alert(incoming, priors, classify(incoming, priors))
    assert decision.kind == "Earlier report received"


def test_repeat_of_same_status_does_not_alert():
    priors = [claim(1, "MISSING", T1)]
    incoming = claim(2, "MISSING", T2, source_id="src_ngo")
    assert not decide_alert(incoming, priors, classify(incoming, priors)).alert


def test_conflict_with_unknown_time_needs_review_with_high_severity():
    priors = [claim(1, "MISSING", T1)]
    incoming = claim(2, "FOUND_SAFE", None, source_id="src_ngo")
    decision = decide_alert(incoming, priors, classify(incoming, priors))
    assert decision.review and decision.severity == Severity.HIGH


def test_same_status_with_unknown_time_is_quiet():
    priors = [claim(1, "MISSING", T1)]
    incoming = claim(2, "MISSING", None, source_id="src_ngo")
    assert not decide_alert(incoming, priors, classify(incoming, priors)).alert


def test_deceased_is_held_and_message_is_gentle():
    c = claim(2, "DECEASED", T2)
    status, reason = delivery_for(c.claim_type, subscription(sms=True))
    assert status == DeliveryStatus.HELD and reason == "SENSITIVE_STATUS"
    assert "coordinator will contact you" in alert_message("Newer report", "Maya", "Police", c)


def test_delivery_depends_on_channels():
    assert delivery_for("FOUND_SAFE", subscription())[0] == DeliveryStatus.NOT_REQUIRED
    assert delivery_for("FOUND_SAFE", subscription(sms=True))[0] == DeliveryStatus.PENDING


def test_summary_cites_latest_dated_report_and_keeps_conflicts():
    claims = [
        claim(1, "MISSING", T1, source_id="src_police"),
        claim(2, "FOUND_SAFE", T2, source_id="src_hospital"),
    ]
    summary = summarize(claims, "PERSON")
    assert summary.cited_claim_id == "clm_2"
    assert summary.label == "Reported found safe"
    assert summary.conflicts == ["clm_1"]
    assert not summary.needs_review


def test_summary_flags_unresolved_conflict():
    claims = [claim(1, "MISSING", T1), claim(2, "FOUND_SAFE", T1, source_id="src_hospital")]
    assert summarize(claims, "PERSON").needs_review


def test_summary_without_status_reports():
    summary = summarize([claim(1, "SEEN_AT_LOCATION", T1)], "PERSON")
    assert summary.cited_claim_id is None
