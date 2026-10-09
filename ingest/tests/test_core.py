from news_ingest.config import load_config
from news_ingest.identity import resolve_source_id
from news_ingest.time import format_utc, parse_feed_timestamp
from news_ingest.urls import normalize_url


def test_config_has_seventeen_sources(config_path):
    assert set(load_config(config_path).enabled_sources()) == {
        "nytimes",
        "ft",
        "borsen",
        "politiken",
        "berlingske",
        "dr",
        "tv2",
        "jp",
        "information",
        "altinget",
        "kristeligt_dagblad",
        "via_ritzau",
        "bbc",
        "economist",
        "guardian",
        "wapo",
        "wsj",
    }


def test_danish_expansion_source_contracts(config_path):
    sources = load_config(config_path).sources
    assert sources["tv2"].identity == "guid"
    assert [(f.id, f.surface) for f in sources["tv2"].feeds] == [("tv2.nyheder", "latest_rss")]
    assert sources["jp"].identity == "url_regex"
    assert sources["jp"].identity_pattern == "ECE([0-9]+)"
    assert [(f.id, f.surface) for f in sources["jp"].feeds] == [
        ("jp.topnyheder", "homepage_rss"),
        ("jp.seneste", "latest_rss"),
    ]
    assert sources["information"].identity == "guid"
    assert sources["altinget"].identity == "guid"
    assert sources["altinget"].feeds[0].surface == "latest_rss"
    assert all(f.surface == "section_rss" for f in sources["altinget"].feeds[1:])
    assert sources["kristeligt_dagblad"].identity == "guid"
    assert [f.surface for f in sources["kristeligt_dagblad"].feeds] == ["latest_rss", "latest_rss"]


def test_jp_identity_uses_ece_article_id(config_path):
    source = load_config(config_path).sources["jp"]
    url = "https://jyllands-posten.dk/erhverv/ECE19639342/nyt-laan-er-en-eskalering/"
    assert resolve_source_id(source, {"id": url}, url) == "19639342"
    assert resolve_source_id("jp", {"id": url}, url) == "19639342"
    assert resolve_source_id(source, {"id": "fallback-guid"}, "https://jyllands-posten.dk/x") == (
        "fallback-guid"
    )


def test_iso_8601_publication_timestamps_parse():
    assert format_utc(parse_feed_timestamp("2026-09-14T11:39:45+0200")) == (
        "2026-09-14T09:39:45.000000Z"
    )
    assert format_utc(parse_feed_timestamp("Mon, 14 Sep 2026 01:15:23 +0200\n")) == (
        "2026-09-13T23:15:23.000000Z"
    )


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
    # WSJ tags each feed's links with its own `mod`; only the canonical URL drops it.
    assert (
        normalize_url("wsj", "https://www.wsj.com/opinion/example?mod=rss_opinion&page=2")
        == "https://www.wsj.com/opinion/example?page=2"
    )
    assert (
        normalize_url("nytimes", "https://www.nytimes.com/a?mod=keep")
        == "https://www.nytimes.com/a?mod=keep"
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


def test_international_expansion_source_contracts(config_path):
    sources = load_config(config_path).sources
    assert sources["bbc"].identity == "url_regex"
    assert sources["economist"].identity == "uuid_guid"
    assert {sources[k].identity for k in ("guardian", "wapo", "wsj")} == {"guid"}
    assert sources["bbc"].feeds[0].surface == "homepage_rss"
    assert sources["guardian"].feeds[0].surface == "homepage_rss"
    assert sources["economist"].feeds[0].surface == "latest_rss"


def test_bbc_identity_ignores_feed_specific_guid_fragment(config_path):
    source = load_config(config_path).sources["bbc"]
    url = "https://www.bbc.co.uk/news/articles/cy5zg41dkqwo?at_medium=RSS&at_campaign=rss"
    assert resolve_source_id(source, {"id": url + "#1"}, url) == "cy5zg41dkqwo"
    assert resolve_source_id(source, {"id": url + "#0"}, url) == "cy5zg41dkqwo"
    video = "https://www.bbc.co.uk/news/videos/cx2z5gjj838o"
    assert resolve_source_id("bbc", {"id": video + "#1"}, video) == "cx2z5gjj838o"
    legacy = "https://www.bbc.co.uk/news/uk-12345678"
    assert resolve_source_id(source, {"id": legacy + "#0"}, legacy) == legacy + "#0"
