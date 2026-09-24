from conftest import BUNDLE, CUTOFF, EDITORIAL_EXAMPLES, PREVIOUS_CUTOFF, read_json
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
    assert set(lead["evidence"][0]) == {"source", "source_id", "title", "description", "published_at", "url", "primary"}
