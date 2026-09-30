import copy

import pytest

from conftest import EDITORIAL_EXAMPLES, read_json
from news_editorial.verdicts import apply_verdicts, sentences_of, validate_verdicts

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"


def edition():
    return read_json(GOLDEN / "edition.json")


def verdicts(*strikes, notes=None):
    """Build a verdicts document with the given (story_id, location, sentence_index, reason) strikes."""
    doc = {"schema_version": 1, "edition_id": "2026-09-15-morning", "stories": []}
    by_story = {}
    for story_id, location, index, reason in strikes:
        by_story.setdefault(story_id, []).append(
            {"location": location, "sentence": index, "verdict": "unsupported", "reason": reason}
        )
    for story_id, items in by_story.items():
        doc["stories"].append({"id": story_id, "sentences": items, "guideline_notes": notes or []})
    return doc


def test_sentences_split_on_terminal_punctuation():
    text = "The count left two seats between the blocs. Kristersson said no. 'It is over,' he added."
    assert sentences_of(text) == [
        "The count left two seats between the blocs.",
        "Kristersson said no.",
        "'It is over,' he added.",
    ]


def test_verdicts_schema_refuses_unknown_verdict():
    doc = verdicts(("russian-frigate-flares-gedser", "standard", 0, "x"))
    doc["stories"][0]["sentences"][0]["verdict"] = "maybe"
    assert validate_verdicts(doc)


def test_no_strikes_leaves_the_edition_unchanged():
    original = edition()
    result = apply_verdicts(original, verdicts(), min_words=0.67)
    assert result["edition"] == original
    assert result["send_back"] == [] and result["struck"] == 0


def test_strike_removes_one_sentence_from_a_paragraph():
    original = edition()
    lead = original["stories"][0]
    target = lead["copy"]["body"]["standard"][0]["text"]
    first = sentences_of(target)[0]
    result = apply_verdicts(original, verdicts(("russian-frigate-flares-gedser", "standard[0]", 1, "no source says it")), min_words=0.0)
    struck = result["edition"]["stories"][0]["copy"]["body"]["standard"][0]["text"]
    assert struck.startswith(first) and struck != target
    assert result["struck"] == 1
    assert result["stories"]["russian-frigate-flares-gedser"]["stands"] is True


def test_striking_the_opening_sentence_sends_the_story_back():
    result = apply_verdicts(edition(), verdicts(("russian-frigate-flares-gedser", "standard[0]", 0, "invented")), min_words=0.0)
    assert result["send_back"] == ["russian-frigate-flares-gedser"]
    assert result["stories"]["russian-frigate-flares-gedser"]["stands"] is False


def test_losing_too_many_words_sends_the_story_back():
    doc = edition()
    story = next(s for s in doc["stories"] if s["role"] == "brief")
    result = apply_verdicts(doc, verdicts((story["id"], "lede", 0, "invented")), min_words=0.67)
    assert story["id"] in result["send_back"]


def test_struck_paragraph_that_empties_is_dropped():
    doc = edition()
    story = doc["stories"][0]
    paragraphs = story["copy"]["body"]["standard"]
    assert len(paragraphs) > 1
    strikes = [("russian-frigate-flares-gedser", "standard[1]", i, "x") for i in range(len(sentences_of(paragraphs[1]["text"])))]
    result = apply_verdicts(doc, verdicts(*strikes), min_words=0.0)
    assert len(result["edition"]["stories"][0]["copy"]["body"]["standard"]) == len(paragraphs) - 1


def test_variant_that_empties_is_dropped():
    doc = edition()
    short = doc["stories"][0]["copy"]["body"]["short"]
    assert len(short) == 1
    strikes = [("russian-frigate-flares-gedser", "short[0]", i, "x") for i in range(len(sentences_of(short[0]["text"])))]
    result = apply_verdicts(doc, verdicts(*strikes), min_words=0.0)
    assert "short" not in result["edition"]["stories"][0]["copy"]["body"]


def test_struck_callout_is_dropped():
    result = apply_verdicts(edition(), verdicts(("russian-frigate-flares-gedser", "callouts[0]", 0, "not verbatim")), min_words=0.0)
    assert len(result["edition"]["stories"][0]["callouts"]) == 1
    assert result["edition"]["stories"][0]["callouts"][0]["kind"] == "timeline"


def test_struck_headline_sends_back_without_editing():
    doc = edition()
    result = apply_verdicts(doc, verdicts(("russian-frigate-flares-gedser", "headline", 0, "wrong")), min_words=0.0)
    assert result["send_back"] == ["russian-frigate-flares-gedser"]
    assert result["edition"]["stories"][0]["copy"]["headline"] == doc["stories"][0]["copy"]["headline"]


def test_final_pass_turns_a_failed_story_into_a_headline_with_a_link():
    doc = edition()
    result = apply_verdicts(doc, verdicts(("russian-frigate-flares-gedser", "standard[0]", 0, "invented")), min_words=0.0, final=True)
    story = result["edition"]["stories"][0]
    assert story["copy"]["body"] == {} and "lede" not in story["copy"] and story["callouts"] == []
    assert "headline_only" in story["limitations"]
    assert result["send_back"] == []
    assert result["fallen"] == ["russian-frigate-flares-gedser"]


def test_final_pass_keeps_the_lede_for_a_brief_capable_story():
    doc = edition()
    brief = next(s for s in doc["stories"] if s["role"] == "brief")
    result = apply_verdicts(doc, verdicts((brief["id"], "lede", 0, "invented")), min_words=0.67, final=True)
    fallen = next(s for s in result["edition"]["stories"] if s["id"] == brief["id"])
    assert fallen["copy"]["lede"]["text"] == fallen["copy"]["headline"]


def test_strict_schema_for_codex_types_every_property_and_requires_all():
    from news_editorial.verdicts import strict_verdicts_schema

    schema = strict_verdicts_schema()
    assert schema["properties"]["schema_version"]["type"] == "integer"
    assert sorted(schema["required"]) == sorted(schema["properties"])
    sentence = schema["properties"]["stories"]["items"]["properties"]["sentences"]["items"]
    assert sorted(sentence["required"]) == sorted(sentence["properties"])
    assert sentence["properties"]["reason"]["type"] == ["string", "null"]
    assert sentence["additionalProperties"] is False


def test_null_fields_from_a_strict_checker_are_dropped():
    from news_editorial.verdicts import without_nulls

    doc = {"schema_version": 1, "edition_id": "x", "checker": None, "stories": [
        {"id": "a", "sentences": [{"location": "headline", "sentence": 0, "verdict": "supported", "reason": None, "passage": None, "cites": None, "text": None}], "guideline_notes": None}]}
    cleaned = without_nulls(doc)
    assert cleaned == {"schema_version": 1, "edition_id": "x", "stories": [
        {"id": "a", "sentences": [{"location": "headline", "sentence": 0, "verdict": "supported"}]}]}
    assert validate_verdicts(cleaned) == []


def test_final_pass_replaces_a_struck_headline_with_the_primary_source_title():
    doc = edition()
    result = apply_verdicts(doc, verdicts(("russian-frigate-flares-gedser", "headline", 0, "wrong")), min_words=0.0, final=True)
    story = result["edition"]["stories"][0]
    primary = next(s for s in story["sources"] if s["primary"])
    assert story["copy"]["headline"] == primary["original_title"]
    assert "headline_short" not in story["copy"]
    assert story["copy"]["headline"] != doc["stories"][0]["copy"]["headline"]
    assert result["fallen"] == ["russian-frigate-flares-gedser"]


def test_struck_short_headline_is_dropped_and_the_story_stands():
    doc = edition()
    result = apply_verdicts(doc, verdicts(("russian-frigate-flares-gedser", "headline_short", 0, "wrong")), min_words=0.0)
    story = result["edition"]["stories"][0]
    assert "headline_short" not in story["copy"]
    assert story["copy"]["headline"] == doc["stories"][0]["copy"]["headline"]
    assert result["send_back"] == [] and result["struck"] == 1


def test_duplicate_verdict_addresses_are_refused_before_anything_is_struck():
    from conftest import BUNDLE, CUTOFF, PREVIOUS_CUTOFF
    from news_editorial.bundle import load_bundle
    from news_editorial.policy import load_policy
    from news_editorial.paths import POLICY_PATH
    from news_editorial.verdicts import check_input, coverage_problems
    from news_editorial.window import build_window

    edition = read_json(EDITORIAL_EXAMPLES / "2026-09-15-morning" / "edition.json")
    window = build_window(load_bundle(BUNDLE), load_policy(POLICY_PATH), cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    doc = check_input(edition, window)
    verdicts = {"schema_version": 1, "edition_id": edition["edition"]["id"], "stories": []}
    for story in doc["stories"]:
        verdicts["stories"].append({"id": story["id"], "sentences": [{"location": s["location"], "sentence": s["sentence"], "verdict": "supported"} for s in story["sentences"]], "guideline_notes": []})
    verdicts["stories"].append(copy.deepcopy(verdicts["stories"][0]))
    problems = coverage_problems(doc, verdicts)
    assert problems["missing"] == [] and problems["unknown"] == []
    assert problems["duplicate"], "the repeated story must be reported"
