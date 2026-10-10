import pytest

from found_core.domain.errors import BadRequest
from found_core.domain.identity import (
    NameParts,
    edit_distance,
    pair_key,
    parse_pair_key,
    score,
)
from found_core.domain.models import Subject
from found_core.domain.normalize import normalize_text


def person(pid: str, name: str, age: int | None = None) -> Subject:
    return Subject(
        id=pid,
        incident_id="inc_1",
        subject_type="PERSON",
        display_name=name,
        name_norm=normalize_text(name),
        age=age,
    )


def test_pair_key_is_sorted_and_parses_back():
    assert pair_key("per_B", "per_A") == "per_A|per_B"
    assert parse_pair_key("per_A|per_B") == ("per_A", "per_B")


@pytest.mark.parametrize("raw", ["per_B|per_A", "per_A|per_A", "per_A", "clm_1|per_B", "a|b|c"])
def test_unsorted_or_odd_pair_keys_are_refused(raw):
    with pytest.raises(BadRequest):
        parse_pair_key(raw)


def test_a_person_cannot_pair_with_themselves():
    with pytest.raises(ValueError):
        pair_key("per_A", "per_A")


def test_name_parts_and_edit_distance():
    assert NameParts.of("maya rawat") == NameParts("maya rawat", "maya", "rawat")
    assert NameParts.of("maya").surname == ""
    assert edit_distance("maya rawat", "maya rawet") == 1
    assert edit_distance("kitten", "sitting") == 3


def test_same_name_alone_is_never_proposed():
    pair = score(
        person("per_1", "Maya Rawat"), person("per_2", "Maya Rawat"), shared_location=False
    )
    assert pair.reasons == ("FULL_NAME_EXACT",) and pair.score == 50
    assert not pair.propose


def test_same_name_and_age_is_proposed_with_its_reasons():
    pair = score(
        person("per_2", "Maya Rawat", 24), person("per_1", "Maya Rawat", 24), shared_location=False
    )
    assert pair.propose and pair.score == 70
    assert pair.reasons == ("FULL_NAME_EXACT", "AGE_EQUAL")
    assert (pair.person_a_id, pair.pair_key) == ("per_1", "per_1|per_2")


def test_a_shortened_surname_with_age_and_place_is_proposed():
    # UC-3: "Maya Rawat, 24" and "Maya R., 24" mentioned at the same place.
    pair = score(
        person("per_1", "Maya Rawat", 24), person("per_2", "Maya R.", 24), shared_location=True
    )
    assert pair.reasons == ("GIVEN_EXACT", "AGE_EQUAL", "SHARED_LOCATION")
    assert pair.score == 55 and pair.propose


def test_a_one_letter_spelling_difference_counts():
    pair = score(
        person("per_1", "Maya Rawat", 24), person("per_2", "Maya Rawet", 25), shared_location=False
    )
    assert pair.reasons == ("GIVEN_EXACT", "NAME_EDIT_DISTANCE_1", "AGE_WITHIN_2")
    assert pair.score == 45 and not pair.propose


def test_a_large_age_gap_counts_against_and_is_not_evidence():
    pair = score(
        person("per_1", "Maya Rawat", 24), person("per_2", "Maya Rawat", 61), shared_location=True
    )
    assert "AGE_DIFF_GT_5" in pair.reasons and pair.score == 35
    assert not pair.propose


def test_same_surname_different_given_name_needs_more_than_a_place():
    pair = score(
        person("per_1", "Anil Rawat", 48), person("per_2", "Pooja Rawat", 17), shared_location=True
    )
    assert pair.reasons == ("SURNAME_EXACT", "AGE_DIFF_GT_5", "SHARED_LOCATION")
    assert not pair.propose


def test_given_initial_and_unknown_age():
    pair = score(person("per_1", "M. Rawat"), person("per_2", "Maya Rawat"), shared_location=True)
    assert pair.reasons == ("SURNAME_EXACT", "GIVEN_INITIAL", "SHARED_LOCATION")
    assert pair.score == 50 and pair.propose
