from news_ingest.config import load_config
from news_ingest.identity import resolve_source_id
from news_ingest.time import format_utc, parse_feed_timestamp
from news_ingest.urls import normalize_url


def test_config_has_six_sources(config_path):
    assert set(load_config(config_path).enabled_sources()) == {
        "nytimes",
        "ft",
        "borsen",
        "politiken",
        "berlingske",
        "dr",
    }


def test_berlingske_source_contract(config_path):
    source = load_config(config_path).sources["berlingske"]
    assert source.identity == "guid"
    assert [(feed.id, feed.surface) for feed in source.feeds] == [
        ("berlingske.latest", "latest_rss"),
        ("berlingske.samfund", "section_rss"),
        ("berlingske.business", "section_rss"),
        ("berlingske.kultur", "section_rss"),
        ("berlingske.opinion", "section_rss"),
    ]


def test_normalization_rules():
    assert (
        normalize_url("ft", "HTTPS://WWW.FT.COM/x?syn-deadBEEF=1&utm_source=x&a=2#f")
        == "https://www.ft.com/x?a=2"
    )
    assert (
        normalize_url("dr", "https://www.dr.dk/a?focusId=A#live") == "https://www.dr.dk/a?focusId=A"
    )
    assert (
        normalize_url(
            "berlingske",
            "https://www.berlingske.dk/politik/example?referrer=RSS&edition=morning#top",
        )
        == "https://www.berlingske.dk/politik/example?edition=morning"
    )
    assert (
        resolve_source_id(
            "berlingske",
            {"guid": "urn:bm:article:a6208a3d-1bf0-5555-a4d6-b0c94759eaf9"},
            "https://www.berlingske.dk/politik/example?referrer=RSS",
        )
        == "urn:bm:article:a6208a3d-1bf0-5555-a4d6-b0c94759eaf9"
    )
    assert resolve_source_id("politiken", {}, "https://politiken.dk/x/art12345/y") == "12345"
    assert (
        format_utc(parse_feed_timestamp("Mon, 01 Jan 2024 12:00:00 +0200"))
        == "2024-01-01T10:00:00.000000Z"
    )
