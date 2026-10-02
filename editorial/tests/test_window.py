from conftest import BUNDLE, CUTOFF, PREVIOUS_CUTOFF, WIRE_ARTICLE, read_json, wired_bundle
from news_editorial.bundle import load_bundle
from news_editorial.window import build_window, write_window

GEDSER_PM = "urn:dr:umbraco:article:70ea5036-5747-4f3f-816a-2577c3b28ab1"


def _window(policy):
    return build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)


def _find(window, source, source_id):
    return next(a for a in window["articles"] if a["source"] == source and a["source_id"] == source_id)


def test_articles_are_numbered_contiguously_newest_first(policy):
    window = _window(policy)
    numbers = [a["n"] for a in window["articles"]]
    assert numbers == list(range(1, len(numbers) + 1))
    published = [a["published_at"] for a in window["articles"]]
    assert published == sorted(published, reverse=True)


def test_sections_come_from_feed_provenance(policy):
    article = _find(_window(policy), "dr", GEDSER_PM)
    assert article["sections"] == ["denmark", "politics"]
    assert article["status"] == "scoring"
    assert article["opinion"] is False


def test_opinion_is_a_flag_not_a_section(policy):
    window = _window(policy)
    opinion = next(a for a in window["articles"] if a["source"] == "borsen" and "/opinion/" in a["source_id"])
    assert opinion["opinion"] is True
    assert "opinion" not in opinion["sections"]


def test_prominence_only_from_ranked_feeds_on_scoring_publishers(policy):
    window = _window(policy)
    borsen = next(a for a in window["articles"] if a["source"] == "borsen" and "open-ai" in a["source_id"])
    assert borsen["prominence"] is not None and 0 < borsen["prominence"]["score"] <= 1
    assert borsen["prominence"]["surface"] == "borsen.homepage"
    dr = _find(window, "dr", GEDSER_PM)
    assert dr["prominence"] is None
    linked = next(a for a in window["articles"] if a["status"] == "linked")
    assert linked["prominence"] is None


def test_newly_observed_since_previous_cutoff(policy):
    window = _window(policy)
    article = _find(window, "dr", GEDSER_PM)
    assert article["newly_observed"] is True
    old = next(a for a in window["articles"] if a["first_seen_at"] < PREVIOUS_CUTOFF)
    assert old["newly_observed"] is False


def test_window_file_carries_bundle_identity(policy, run_dir):
    window = _window(policy)
    write_window(window, run_dir)
    saved = read_json(run_dir / "window.json")
    assert saved["bundle"]["input_id"] == "export-2026-09-15-0800"
    assert saved["bundle"]["manifest_sha256"].startswith("sha256:")
    assert saved["cutoff_at"] == CUTOFF
    assert (run_dir / "window.md").exists()


def test_wire_copy_is_marked_with_its_agency(policy):
    window = build_window(wired_bundle(), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    assert _find(window, "kristeligt_dagblad", WIRE_ARTICLE)["wire"] == "ritzau"
    assert _find(window, "dr", GEDSER_PM)["wire"] is None


def test_the_reading_view_flags_wire_copy(policy, run_dir):
    window = build_window(wired_bundle(), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)
    write_window(window, run_dir)
    wire = _find(window, "kristeligt_dagblad", WIRE_ARTICLE)
    lines = (run_dir / "window.md").read_text().splitlines()
    assert next(line for line in lines if line.startswith(f"- [{wire['n']}] ")).split(": ")[0].endswith(" wire:ritzau")
    own = _find(window, "dr", GEDSER_PM)
    assert "wire:" not in next(line for line in lines if line.startswith(f"- [{own['n']}] ")).split(": ")[0]
