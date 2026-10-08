from found_core.domain.models import Source
from found_core.domain.normalize import detect_mentions, excerpt, name_tokens, normalize_text


def _src(sid: str, name: str) -> Source:
    return Source(
        id=sid,
        incident_id="inc_1",
        name=name,
        name_norm=normalize_text(name),
        source_type="NGO",
    )


def test_normalize_text_folds_case_punctuation_and_spaces():
    assert normalize_text("  Central-Hospital,  DEMO!! ") == "central hospital demo"


def test_name_tokens_are_unique_and_skip_single_letters():
    assert name_tokens("Maya R. Rawat maya") == ["maya", "rawat"]


def test_detect_mentions_matches_whole_words_in_order():
    hospital = _src("src_h", "Central Hospital Demo")
    police = _src("src_p", "District Police Demo")
    text = "Per District Police Demo and, later, CENTRAL hospital demo: admitted."
    assert detect_mentions(text, [hospital, police]) == [police, hospital]


def test_detect_mentions_ignores_partial_words_and_excluded_source():
    cross = _src("src_c", "Red Cross")
    own = _src("src_o", "Flood Relief Demo")
    text = "Volunteers at Red Crossing; Flood Relief Demo reports."
    assert detect_mentions(text, [cross, own], exclude_id="src_o") == []


def test_detect_mentions_skips_very_short_names():
    short = _src("src_s", "MSF")
    assert detect_mentions("MSF says so", [short]) == []


def test_excerpt_keeps_short_text_and_cuts_long_text_on_a_word():
    assert excerpt("  Maya   Rawat,\n24 ") == "Maya Rawat, 24"
    assert excerpt("Family reports Maya Rawat missing", limit=20) == "Family reports Maya..."
    assert excerpt("abcdefghijklmnop", limit=5) == "abcde..."
