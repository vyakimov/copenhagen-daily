import json
from pathlib import Path

from news_editorial.verify import verify_live

EDITION = "2026-09-30-morning"
PAGE = b'<!doctype html><link rel="stylesheet" href="/a/broadsheet-v3/web.css"><title>Copenhagen Daily</title>'
MANIFEST = b'{"edition_id":"2026-09-30-morning","files":[]}'


def publish_root(tmp_path: Path, edition: str = EDITION, date: str = "2026-09-30") -> Path:
    live = tmp_path / "live"
    (live / "n" / edition).mkdir(parents=True)
    (live / "latest.json").write_text(json.dumps({"web": {"edition_id": edition, "date": date, "status": "published"}}))
    (live / "index.html").write_bytes(PAGE)
    (live / "n" / edition / "manifest.json").write_bytes(MANIFEST)
    (live / "n" / edition / "edition.json").write_text(json.dumps({"edition": {"id": edition, "number": 14}}))
    return tmp_path


class Site:
    """A fake live site: a dict of path -> (status, headers, body); missing paths are 404."""

    def __init__(self, root: Path, **overrides):
        live = root / "live"
        self.pages = {
            "/latest.json": (200, {"x-robots-tag": "noindex, nofollow"}, (live / "latest.json").read_bytes()),
            "/": (200, {}, PAGE),
            f"/n/{EDITION}/manifest.json": (200, {}, MANIFEST),
            "/a/broadsheet-v3/web.css": (200, {}, b"body{}"),
        }
        self.pages.update(overrides)
        self.requests: list[str] = []

    def __call__(self, url: str):
        path = url.removeprefix("https://example.test")
        self.requests.append(path)
        return self.pages.get(path, (404, {}, b""))


def test_a_matching_site_is_ok(tmp_path):
    root = publish_root(tmp_path)
    report = verify_live(root, "https://example.test", Site(root), today="2026-09-30")
    assert report["state"] == "ok" and report["fixable"] is False
    assert report["live_edition"] == EDITION and report["local_edition"] == EDITION
    assert report["number"] == 14
    assert report["problems"] == []


def test_an_unreachable_site_is_reported_and_not_fixable(tmp_path):
    root = publish_root(tmp_path)

    def down(url):
        raise OSError("connection refused")

    report = verify_live(root, "https://example.test", down, today="2026-09-30")
    assert report["state"] == "unreachable" and report["fixable"] is False


def test_a_site_behind_the_local_paper_is_not_delivered_and_fixable(tmp_path):
    root = publish_root(tmp_path)
    stale = json.dumps({"web": {"edition_id": "2026-09-29-morning", "date": "2026-09-29"}}).encode()
    site = Site(root, **{"/latest.json": (200, {"x-robots-tag": "noindex"}, stale)})
    report = verify_live(root, "https://example.test", site, today="2026-09-30")
    assert report["state"] == "not_delivered" and report["fixable"] is True
    assert report["live_edition"] == "2026-09-29-morning"


def test_a_changed_manifest_or_page_counts_as_not_delivered(tmp_path):
    root = publish_root(tmp_path)
    site = Site(root, **{f"/n/{EDITION}/manifest.json": (200, {}, b'{"edition_id":"2026-09-30-morning","files":[1]}')})
    report = verify_live(root, "https://example.test", site, today="2026-09-30")
    assert report["state"] == "not_delivered" and report["fixable"] is True
    assert any("manifest" in p for p in report["problems"])


def test_a_missing_stylesheet_is_broken_and_fixable_and_a_missing_robots_header_is_not(tmp_path):
    root = publish_root(tmp_path)
    site = Site(root, **{"/a/broadsheet-v3/web.css": (404, {}, b"")})
    report = verify_live(root, "https://example.test", site, today="2026-09-30")
    assert report["state"] == "broken" and report["fixable"] is True
    site = Site(root, **{"/latest.json": (200, {}, (root / "live" / "latest.json").read_bytes())})
    report = verify_live(root, "https://example.test", site, today="2026-09-30")
    assert report["state"] == "broken" and report["fixable"] is False
    assert any("robots" in p for p in report["problems"])


def test_a_delivered_but_old_paper_reports_no_edition_today_or_a_run_in_progress(tmp_path):
    root = publish_root(tmp_path)
    report = verify_live(root, "https://example.test", Site(root), today="2026-10-01")
    assert report["state"] == "no_edition_today" and report["fixable"] is False
    report = verify_live(root, "https://example.test", Site(root), today="2026-10-01", run_in_progress=True)
    assert report["state"] == "run_in_progress"


def test_an_empty_publish_root_is_reported(tmp_path):
    report = verify_live(tmp_path, "https://example.test", Site(publish_root(tmp_path / "other")), today="2026-09-30")
    assert report["state"] == "no_local_edition" and report["fixable"] is False


def test_a_pointer_that_differs_in_any_field_is_not_delivered(tmp_path):
    root = publish_root(tmp_path)
    local = json.loads((root / "live" / "latest.json").read_text())
    local["web"]["date"] = "1900-01-01"
    site = Site(root, **{"/latest.json": (200, {"x-robots-tag": "noindex"}, json.dumps(local).encode())})
    report = verify_live(root, "https://example.test", site, today="2026-09-30")
    assert report["state"] == "not_delivered" and report["fixable"] is True
    assert report["live_edition"] == EDITION
