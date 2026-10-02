from conftest import BUNDLE, CUTOFF, EDITORIAL_EXAMPLES, PREVIOUS_CUTOFF, WIRE_ARTICLE, read_json, wired_bundle
from news_editorial.build import build_edition
from news_editorial.bundle import load_bundle
from news_editorial.verdicts import check_input, sentences_of
from news_editorial.window import build_window

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"


def test_check_input_lists_every_sentence_with_its_location(policy):
    edition = read_json(GOLDEN / "edition.json")
    window = build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    doc = check_input(edition, window)
    assert doc["edition_id"] == "2026-09-15-morning"
    lead = doc["stories"][0]
    locations = [s["location"] for s in lead["sentences"]]
    assert locations[0] == "headline" and "deck" in locations and "standard[0]" in locations
    first_standard = [s for s in lead["sentences"] if s["location"] == "standard[0]"]
    assert [s["sentence"] for s in first_standard] == list(range(len(first_standard)))
    assert first_standard[0]["text"] == sentences_of(edition["stories"][0]["copy"]["body"]["standard"][0]["text"])[0]
    assert first_standard[0]["cites"] == edition["stories"][0]["copy"]["body"]["standard"][0]["sources"]
    callouts = [s for s in lead["sentences"] if s["location"].startswith("callouts")]
    assert len(callouts) == 2 and "Aggressive" in callouts[0]["text"]


def test_check_input_attaches_the_evidence_from_the_window(policy):
    edition = read_json(GOLDEN / "edition.json")
    window = build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    doc = check_input(edition, window)
    lead = doc["stories"][0]
    assert len(lead["evidence"]) == len(edition["stories"][0]["sources"])
    dr = next(e for e in lead["evidence"] if e["source"] == "dr")
    assert dr["title"] and dr["description"] and dr["published_at"] and dr["url"].startswith("https://")
    assert set(lead["evidence"][0]) == {"source", "source_id", "title", "description", "authors", "categories", "published_at", "url", "primary", "wire"}
    assert any(e["authors"] for story in doc["stories"] for e in story["evidence"])
    headline = lead["sentences"][0]
    assert headline["location"] == "headline"
    assert sorted(headline["cites"]) == sorted({e["source"] for e in lead["evidence"]})


def test_check_input_includes_the_short_headline(policy):
    edition = read_json(GOLDEN / "edition.json")
    window = build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    story = check_input(edition, window)["stories"][0]
    short = [s for s in story["sentences"] if s["location"] == "headline_short"]
    assert len(short) == 1 and short[0]["text"] == edition["stories"][0]["copy"]["headline_short"]


def test_check_input_tells_the_checker_which_evidence_is_wire_copy(policy):
    bundle = wired_bundle()
    edition = build_edition(read_json(GOLDEN / "spec.json"), bundle, feeds=read_json(GOLDEN / "feeds.json"))
    window = build_window(bundle, policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    evidence = check_input(edition, window)["stories"][0]["evidence"]
    assert next(e for e in evidence if e["source_id"] == WIRE_ARTICLE)["wire"] == "ritzau"
    assert all(e["wire"] is None for e in evidence if e["source_id"] != WIRE_ARTICLE)
