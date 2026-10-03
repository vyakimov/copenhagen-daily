import copy

import pytest
from conftest import BUNDLE, EDITORIAL_EXAMPLES, WIRE_ARTICLE, read_json, wired_bundle

from news_editorial.build import BuildError, build_edition, validate_spec
from news_editorial.bundle import load_bundle
from news_editorial.contract import validate_edition

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"


def golden_spec():
    return read_json(GOLDEN / "spec.json")


def test_golden_spec_matches_the_spec_schema():
    assert validate_spec(golden_spec()) == []


def test_spec_schema_refuses_an_unknown_field():
    spec = golden_spec()
    spec["stories"][0]["colour"] = "purple"
    errors = validate_spec(spec)
    assert errors and "/stories/0/colour" in errors[0]


def test_golden_spec_rebuilds_the_archived_edition():
    spec = golden_spec()
    archived = read_json(GOLDEN / "edition.json")
    spec["edition"]["generated_at"] = archived["edition"]["generated_at"]
    edition = build_edition(spec, load_bundle(BUNDLE), feeds=read_json(GOLDEN / "feeds.json"))
    assert validate_edition(edition) == []
    edition["inputs"] = archived["inputs"]  # the fixture is a cut of the real bundle, so its digest differs
    assert edition == archived


def test_sources_may_be_window_numbers():
    spec = golden_spec()
    bundle = load_bundle(BUNDLE)
    brief = next(s for s in spec["stories"] if s["role"] == "brief")
    publisher, suffix = brief["sources"][0].split(":", 1)
    article = next(a for a in bundle.articles if a["source"] == publisher and a["source_id"].endswith(suffix))
    window = {"articles": [{"n": 7, "source": article["source"], "source_id": article["source_id"]}]}
    brief["sources"][0] = 7
    edition = build_edition(spec, bundle, feeds=read_json(GOLDEN / "feeds.json"), window=window)
    built = next(s for s in edition["stories"] if s["id"] == brief["id"])
    assert built["sources"][0]["source_id"] == article["source_id"]


def test_citation_outside_sources_is_refused():
    spec = golden_spec()
    spec["stories"][1]["standard"][0][1] = ["nytimes"]
    with pytest.raises(BuildError) as info:
        build_edition(spec, load_bundle(BUNDLE), feeds=read_json(GOLDEN / "feeds.json"))
    assert "nytimes" in str(info.value)


def test_ambiguous_source_reference_is_refused():
    spec = golden_spec()
    spec["stories"][0]["sources"][0] = "dr:"
    with pytest.raises(BuildError):
        build_edition(spec, load_bundle(BUNDLE), feeds=read_json(GOLDEN / "feeds.json"))


def test_published_story_id_is_refused():
    spec = golden_spec()
    memory = {"editions": [{"id": "2026-09-14-midday", "stories": [{"id": spec["stories"][0]["id"]}]}]}
    with pytest.raises(BuildError) as info:
        build_edition(spec, load_bundle(BUNDLE), feeds=read_json(GOLDEN / "feeds.json"), memory=memory)
    assert "2026-09-14-midday" in str(info.value)


def test_headline_only_story_is_marked(policy):
    spec = golden_spec()
    bundle = load_bundle(BUNDLE)
    # Find a cited article without a description and make a headline-only brief from it.
    brief = next(s for s in spec["stories"] if s["role"] == "brief")
    publisher, suffix = brief["sources"][0].split(":", 1)
    edition = build_edition(spec, bundle, feeds=read_json(GOLDEN / "feeds.json"))
    story = next(s for s in edition["stories"] if s["id"] == brief["id"])
    assert "digest_of_rss_description" in story["limitations"]


def test_only_the_lead_is_required_on_the_device_when_the_spec_is_silent():
    from news_editorial.build import assign_device_participation

    stories = [{"id": "lead", "role": "lead"}] + [{"id": f"s{i}", "role": "secondary"} for i in range(5)] + [
        {"id": f"b{i}", "role": "brief"} for i in range(15)
    ]
    assigned = assign_device_participation(stories)
    assert [s["id"] for s in assigned if s["device_participation"] == "required"] == ["lead"]
    optional = [s["id"] for s in assigned if s["device_participation"] == "optional"]
    assert optional == [f"s{i}" for i in range(5)] + [f"b{i}" for i in range(15)]
    # an explicit value in the spec is kept
    kept = assign_device_participation([{"id": "lead", "role": "lead"}, {"id": "s0", "role": "secondary", "device_participation": "reserve"}])
    assert kept[1]["device_participation"] == "reserve"


def test_a_spec_without_device_fields_builds_an_edition_the_device_can_fit():
    spec = copy.deepcopy(golden_spec())
    for story in spec["stories"]:
        story.pop("device", None)
        story.pop("fallback", None)
    doc = build_edition(spec, load_bundle(BUNDLE), feeds=read_json(GOLDEN / "feeds.json"))
    assert [s["id"] for s in doc["stories"] if s["device_participation"] == "required"] == [doc["stories"][0]["id"]]
    assert doc["fit_policy"]["omittable_story_ids"] == [s["id"] for s in doc["stories"] if s["device_participation"] == "optional"]


def test_a_wire_article_is_credited_to_its_agency_and_links_to_its_carrier():
    edition = build_edition(golden_spec(), wired_bundle(), feeds=read_json(GOLDEN / "feeds.json"))
    assert validate_edition(edition) == []
    assert edition["schema_version"] == 2
    sources = [s for story in edition["stories"] for s in story["sources"]]
    wire = next(s for s in sources if s["source_id"] == WIRE_ARTICLE)
    assert wire["wire"] == "ritzau"
    assert wire["source"] == "kristeligt_dagblad" and "kristeligt-dagblad.dk" in wire["url"]
    assert all("wire" not in s for s in sources if s is not wire)


def test_story_copy_may_declare_definitions_but_the_spec_entry_never_carries_them():
    from news_editorial.build import spec_story, validate_story_copy

    copy = {"headline": "H", "lede": ["A sentence.", ["dr"]], "definitions": [{"term": "X", "definition": "a thing", "wikipedia": "X"}]}
    assert validate_story_copy(copy, "brief") == []
    assert "definitions" not in spec_story({"id": "s", "role": "brief", "kicker": "K", "sources": [1]}, copy)
    bad = {**copy, "definitions": [{"term": "X", "definition": "a thing"}]}
    assert validate_story_copy(bad, "brief")
