import json
from collections import namedtuple
from datetime import UTC, datetime, timedelta

from news_ingest.db import Database
from news_ingest.health import health
from news_ingest.time import format_utc

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
MB = 1048576


def database(tmp_path, samples):
    """A database whose collection runs recorded these (hours ago, used MB) samples."""
    path = tmp_path / "news.sqlite3"
    db = Database(path)
    for hours, used in samples:
        db.con.execute(
            "INSERT INTO fetch_runs(run_id,started_at,status,summary_json) VALUES(?,?,?,?)",
            (
                f"run-{hours}",
                format_utc(NOW - timedelta(hours=hours)),
                "success",
                json.dumps({"database_used_bytes": used * MB}),
            ),
        )
    db.con.commit()
    db.close()
    return path


def report(path, monkeypatch, free=10**12, alert=250):
    monkeypatch.setattr("news_ingest.health.now_utc", lambda: NOW)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("news_ingest.health.shutil.disk_usage", lambda _: usage(0, 0, free))
    return health(path, growth_alert_mb_per_day=alert)


def test_growth_is_measured_over_the_last_week(tmp_path, monkeypatch):
    # Ten days of samples; only the last seven count: 1000 MB to 1600 MB over 6 days.
    path = database(tmp_path, [(240, 100), (144, 1000), (72, 1300), (0, 1600)])
    result = report(path, monkeypatch)
    assert result["database"]["growth_bytes_per_day"] == 100 * MB
    assert result["database"]["growth_window_days"] == 6
    assert result["status"] == "healthy"
    assert result["database"]["file_bytes"] > 0
    assert result["database"]["used_bytes"] > 0


def test_fast_growth_and_low_disk_degrade_health(tmp_path, monkeypatch):
    path = database(tmp_path, [(48, 1000), (0, 1800)])
    result = report(path, monkeypatch, free=1, alert=250)
    assert result["status"] == "degraded"
    assert result["reasons"] == ["database_growth:400MB_per_day", "disk_headroom"]


def test_growth_waits_for_a_whole_day_of_samples(tmp_path, monkeypatch):
    path = database(tmp_path, [(12, 1000), (0, 5000)])
    result = report(path, monkeypatch, alert=1)
    assert result["database"]["growth_bytes_per_day"] is None
    assert result["status"] == "healthy"
