import copy
import json

import pytest

from conftest import BUNDLE, EDITORIAL_EXAMPLES, read_json
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
