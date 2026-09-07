from news_ingest.config import load_config
from news_ingest.identity import resolve_source_id
from news_ingest.time import format_utc, parse_feed_timestamp
from news_ingest.urls import normalize_url


def test_config_has_five_sources(config_path):
    assert set(load_config(config_path).enabled_sources()) == {
        "nytimes",
        "ft",
        "borsen",
        "politiken",
        "dr",
    }


def test_normalization_rules():
    assert (
        normalize_url("ft", "HTTPS://WWW.FT.COM/x?syn-deadBEEF=1&utm_source=x&a=2#f")
        == "https://www.ft.com/x?a=2"
    )
    assert (
        normalize_url("dr", "https://www.dr.dk/a?focusId=A#live") == "https://www.dr.dk/a?focusId=A"
    )
    assert resolve_source_id("politiken", {}, "https://politiken.dk/x/art12345/y") == "12345"
    assert (
        format_utc(parse_feed_timestamp("Mon, 01 Jan 2024 12:00:00 +0200"))
        == "2024-01-01T10:00:00.000000Z"
    )
