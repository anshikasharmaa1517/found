import pytest
from pydantic import ValidationError

from found_core.domain.enums import InvestigationStatus as S
from found_core.domain.findings import (
    REASON_PRIORITY,
    FindingInput,
    decide_outcome,
    quotes,
    review_priority,
    validate_finding,
)
from tests.unit.factories import claim

RELAY_TEXT = "According to Central Hospital Demo, Maya R. was admitted to ward 3."
SOURCE_TEXT = "Maya Rawat admitted to ward 3 at 07:40, stable."


def relay_claim():
    return claim(2, "FOUND_SAFE", None, source_id="src_ngo").model_copy(
        update={"id": "clm_relay", "original_text": RELAY_TEXT, "mentioned_source_ids": ("src_h",)}
    )


def source_claim():
    return claim(1, "FOUND_SAFE", None, source_id="src_h").model_copy(
        update={"id": "clm_src", "original_text": SOURCE_TEXT}
    )


CITED = {"clm_relay": relay_claim(), "clm_src": source_claim()}
RELAY_CITE = {"claim_id": "clm_relay", "excerpt": "According to Central Hospital Demo"}
SOURCE_CITE = {"claim_id": "clm_src", "excerpt": "admitted to ward 3 at 07:40"}


def finding(**overrides):
    data = {
        "attribution": "RELAY",
        "referenced_source_id": "src_h",
        "comparison": "SUPPORTS",
        "summary": "The NGO repeats the hospital's report.",
        "citations": [RELAY_CITE, SOURCE_CITE],
        **overrides,
    }
    return FindingInput.model_validate(data)


def codes(f, has_reports=True, cited=CITED):
    return [e.code for e in validate_finding(f, relay_claim(), cited, has_reports)]


def test_valid_relay_finding_has_no_errors():
    assert codes(finding()) == []


def test_source_outside_the_mention_menu_is_refused():
    assert "SOURCE_NOT_IN_MENU" in codes(finding(referenced_source_id="src_other"))


def test_unknown_or_out_of_incident_claim_is_refused():
    f = finding(citations=[RELAY_CITE, {"claim_id": "clm_x", "excerpt": "some words here"}])
    assert "UNKNOWN_CLAIM" in codes(f)


@pytest.mark.parametrize(
    "excerpt, code",
    [
        ("short", "EXCERPT_LENGTH"),
        ("x" * 301, "EXCERPT_LENGTH"),
        ("According to the Central Hospital", "EXCERPT_NOT_FOUND"),
        ("according to central hospital demo", "EXCERPT_NOT_FOUND"),
    ],
)
def test_excerpts_must_be_verbatim_and_sized(excerpt, code):
    f = finding(citations=[{"claim_id": "clm_relay", "excerpt": excerpt}, SOURCE_CITE])
    assert code in codes(f)


def test_whitespace_differences_are_ignored():
    assert quotes("According  to\nCentral Hospital", RELAY_TEXT)
    spaced = {"claim_id": "clm_relay", "excerpt": "According\tto  Central"}
    f = finding(citations=[spaced, SOURCE_CITE])
    assert codes(f) == []


def test_investigated_claim_must_be_cited():
    assert "CLAIM_NOT_CITED" in codes(finding(citations=[SOURCE_CITE]))


def test_relay_of_a_source_with_reports_must_compare_and_cite_it():
    assert "COMPARISON_REQUIRED" in codes(finding(comparison="NOT_APPLICABLE"))
    assert "SOURCE_NOT_CITED" in codes(finding(citations=[RELAY_CITE]))


@pytest.mark.parametrize(
    "overrides, has_reports",
    [
        ({"referenced_source_id": None, "attribution": "DIRECT"}, True),
        ({"referenced_source_id": None}, True),
        ({}, False),
    ],
)
def test_nothing_to_compare_needs_not_applicable(overrides, has_reports):
    f = finding(**overrides, citations=[RELAY_CITE])
    assert "NOTHING_TO_COMPARE" in codes(f, has_reports)
    assert codes(finding(**overrides, comparison="NOT_APPLICABLE", citations=[RELAY_CITE]),
                 has_reports) == []  # fmt: skip


@pytest.mark.parametrize(
    "data",
    [
        {"attribution": "MAYBE"},
        {"comparison": "AGREES"},
        {"summary": ""},
        {"summary": "x" * 601},
        {"citations": []},
        {"citations": [RELAY_CITE] * 9},
        {"confidence": 0.9},
    ],
)
def test_input_shape_is_strict(data):
    with pytest.raises(ValidationError):
        finding(**data)


@pytest.mark.parametrize(
    "overrides, has_reports, status, reasons, priority",
    [
        ({"attribution": "DIRECT", "referenced_source_id": None}, True, S.COMPLETED, (), None),
        ({"attribution": "DIRECT"}, True, S.NEEDS_REVIEW, ("DIRECT_BUT_NAMES_SOURCE",), 2),
        ({}, True, S.NEEDS_REVIEW, ("RELAY_NOT_FIRST_HAND",), 3),
        ({"comparison": "DIFFERS"}, True, S.NEEDS_REVIEW, ("RELAY_DIFFERS_FROM_SOURCE",), 1),
        ({"comparison": "UNCLEAR"}, True, S.NEEDS_REVIEW, ("COMPARISON_UNCLEAR",), 2),
        ({"comparison": "NOT_APPLICABLE"}, False, S.NEEDS_REVIEW, ("SOURCE_NOT_FOUND",), 2),
        ({"referenced_source_id": None}, True, S.NEEDS_REVIEW, ("SOURCE_NOT_FOUND",), 2),
        ({"attribution": "UNCLEAR"}, True, S.NEEDS_REVIEW, ("ATTRIBUTION_UNCLEAR",), 2),
    ],
)
def test_outcome_table(overrides, has_reports, status, reasons, priority):
    outcome = decide_outcome(finding(**overrides), has_reports)
    assert (outcome.status, outcome.reasons, outcome.priority) == (status, reasons, priority)


def test_agreeing_relay_is_never_completed():
    assert decide_outcome(finding(comparison="SUPPORTS"), True).status == S.NEEDS_REVIEW


def test_priority_is_the_most_urgent_reason():
    assert review_priority(["RELAY_NOT_FIRST_HAND", "RELAY_DIFFERS_FROM_SOURCE"]) == 1
    assert review_priority([]) is None
    assert set(REASON_PRIORITY.values()) == {1, 2, 3}
