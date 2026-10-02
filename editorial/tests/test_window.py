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


TRUMP_TRUCE = "urn:bm:article:0941a2fc-37ca-5ab5-ae24-e8b807224a03"


def _line_for(path, n):
    return next(line for line in path.read_text().splitlines() if line.startswith(f"- [{n}] "))


def test_sections_also_come_from_publisher_categories(policy):
    """Berlingske's samfund feed carries world, politics and domestic news side by side; the feed maps to
    nothing and the article's own category tags supply the section."""
    article = _find(_window(policy), "berlingske", TRUMP_TRUCE)
    assert article["categories"] == ["Internationalt", "Samfund"]
    assert article["sections"] == ["world"]


def test_long_descriptions_are_cut_in_the_reading_view(policy, run_dir):
    window = _window(policy)
    article = _find(window, "dr", GEDSER_PM)
    article["description"] = "Første sætning om fregatten. " + "Mere tekst her. " * 60 + "Sidste sætning."
    write_window(window, run_dir)
    lines = (run_dir / "window.md").read_text().splitlines()
    head = _line_for(run_dir / "window.md", article["n"])
    body = lines[lines.index(head) + 1]
    assert body.startswith("  Første sætning om fregatten.")
    assert body.endswith(". …") and len(body) < 560
    assert read_json(run_dir / "window.json")["articles"][article["n"] - 1]["description"] == article["description"]


def test_short_descriptions_are_not_cut(policy, run_dir):
    window = _window(policy)
    article = _find(window, "dr", GEDSER_PM)
    write_window(window, run_dir)
    lines = (run_dir / "window.md").read_text().splitlines()
    head = _line_for(run_dir / "window.md", article["n"])
    assert lines[lines.index(head) + 1] == "  " + article["description"]


def test_identical_text_is_listed_once_and_pointed_to(policy, run_dir):
    window = _window(policy)
    first = _find(window, "dr", GEDSER_PM)
    twin = next(a for a in window["articles"] if a["source"] == "tv2" and a["published_at"] >= first["published_at"][:4])
    twin["title"] = first["title"].upper() + " "
    twin["description"] = first["description"].upper()
    write_window(window, run_dir)
    assert _line_for(run_dir / "window.md", twin["n"]).endswith(f"same text as [{first['n']}] dr")
    assert first["title"] in _line_for(run_dir / "window.md", first["n"])


def test_the_same_headline_over_a_different_description_keeps_its_description(policy, run_dir):
    """A rolling page files the same headline over new text; that is evidence, not a duplicate."""
    window = _window(policy)
    first = _find(window, "dr", GEDSER_PM)
    twin = next(a for a in window["articles"] if a["source"] == "tv2" and a["description"] and a["published_at"] > "2026-09-14T08:00")
    twin["title"] = first["title"]
    twin["description"] = "En helt anden beskrivelse af en anden udvikling i sagen, som ikke ligner den første."
    write_window(window, run_dir)
    lines = (run_dir / "window.md").read_text().splitlines()
    head = _line_for(run_dir / "window.md", twin["n"])
    assert first["title"] in head and head.endswith(f"(same headline as [{first['n']}] dr)")
    assert lines[lines.index(head) + 1] == "  " + twin["description"]


def test_a_headline_only_repeat_points_to_the_first(policy, run_dir):
    window = _window(policy)
    first = _find(window, "dr", GEDSER_PM)
    twin = next(a for a in window["articles"] if a["source"] == "tv2" and a is not first)
    twin["title"] = first["title"]
    twin["description"] = None
    write_window(window, run_dir)
    assert _line_for(run_dir / "window.md", twin["n"]).endswith(f"same text as [{first['n']}] dr")


def test_linked_publishers_are_listed_in_their_own_file(policy, run_dir):
    window = _window(policy)
    write_window(window, run_dir)
    main = (run_dir / "window.md").read_text()
    linked = (run_dir / "window-linked.md").read_text()
    assert "## guardian (linked" in linked and "## guardian" not in main
    assert "## dr (scoring" in main and "## dr" not in linked
    assert "window-linked.md" in main
    guardian = next(a for a in window["articles"] if a["source"] == "guardian")
    assert _line_for(run_dir / "window-linked.md", guardian["n"]).endswith(guardian["title"])
