from conftest import FIXTURES
from news_editorial.freshness import latest_activated, staleness

PUBLISH_ROOT = FIXTURES / "publish-root"


def test_latest_activated_edition_is_the_highest_sequence():
    latest = latest_activated(PUBLISH_ROOT)
    assert latest["edition_id"] == "2026-09-19-evening"
    assert latest["cutoff_at"] == "2026-09-19T19:49:28.000000Z"


def test_staleness_measures_hours_since_the_cutoff():
    report = staleness(PUBLISH_ROOT, now="2026-09-20T19:49:28.000000Z", max_age_hours=30)
    assert report["age_hours"] == 24.0 and report["stale"] is False
    report = staleness(PUBLISH_ROOT, now="2026-09-21T08:00:00.000000Z", max_age_hours=30)
    assert report["stale"] is True and report["edition_id"] == "2026-09-19-evening"


def test_empty_publish_root_is_stale(tmp_path):
    report = staleness(tmp_path, now="2026-09-21T08:00:00.000000Z", max_age_hours=30)
    assert report["stale"] is True and report["edition_id"] is None
