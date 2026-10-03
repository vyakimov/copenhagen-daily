import json

from news_editorial.lookups import summary_url, wikipedia_summary


def test_summary_url_targets_wikipedia_only():
    assert summary_url("Borris Skydeterræn") == "https://en.wikipedia.org/api/rest_v1/page/summary/Borris_Skydeterr%C3%A6n"
    assert summary_url("da:Borris Skydeterræn").startswith("https://da.wikipedia.org/")
    assert summary_url("../evil") == "https://en.wikipedia.org/api/rest_v1/page/summary/..%2Fevil"


def test_a_found_article_yields_its_extract_and_page():
    body = json.dumps({"title": "Elon Musk", "extract": "Elon Musk is a businessman.", "type": "standard",
                       "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Elon_Musk"}}}).encode()
    row = wikipedia_summary("Elon Musk", fetch=lambda url, timeout: (200, body))
    assert row["status"] == "found" and row["extract"] == "Elon Musk is a businessman."
    assert row["url"] == "https://en.wikipedia.org/wiki/Elon_Musk" and row["requested"] == "Elon Musk"


def test_a_missing_article_or_a_failed_fetch_never_raises():
    assert wikipedia_summary("Nope", fetch=lambda url, timeout: (404, b""))["status"] == "missing"
    assert wikipedia_summary("Nope", fetch=lambda url, timeout: (503, b""))["status"] == "unavailable"

    def boom(url, timeout):
        raise OSError("no network")

    row = wikipedia_summary("Nope", fetch=boom)
    assert row["status"] == "unavailable" and "no network" in row["error"]
    assert wikipedia_summary("Nope", fetch=lambda url, timeout: (200, b"not json"))["status"] == "unavailable"
    assert wikipedia_summary("Nope", fetch=lambda url, timeout: (200, b'{"extract": ""}'))["status"] == "missing"
