"""A failed poll counts against its feed, and health reports the feed once the threshold is reached."""

from news_ingest.db import Database
from news_ingest.health import health


def test_a_failed_poll_increments_the_feed_failure_count_and_health_reports_it(tmp_path):
    path = tmp_path / "news.sqlite3"
    db = Database(path)
    run = db.start_run()
    for _ in range(3):
        poll = db.preallocate_poll(run, "dr.senestenyt", "dr", db.state("dr.senestenyt"))
        db.fail_poll(
            poll, ConnectionError("boom"), "dr.senestenyt", "dr", "https://example.org/feed"
        )
    state = db.state("dr.senestenyt")
    assert state["consecutive_failures"] == 3
    assert "boom" in state["last_error_json"] and "ConnectionError" in state["last_error_json"]
    assert state["last_successful_poll_at"] is None
    report = health(path, threshold=3)
    assert report["status"] == "degraded" and "feed_failures:dr.senestenyt" in report["reasons"]
    poll = db.preallocate_poll(run, "dr.senestenyt", "dr", db.state("dr.senestenyt"))
    db.commit_not_modified(poll, "dr.senestenyt", "dr", "https://example.org/feed")
    assert db.state("dr.senestenyt")["consecutive_failures"] == 0
    assert health(path, threshold=3)["status"] == "healthy"


def test_health_answers_without_reading_the_whole_database(tmp_path, monkeypatch):
    """The feed check runs on every poll and twice per edition; a full integrity check reads every
    page of a multi-gigabyte database and crossed the desk's two-minute budget on 9 October 2026."""
    path = tmp_path / "news.sqlite3"
    Database(path)
    import news_ingest.health as module

    statements = []
    real_connect = module.connect

    class Spy:
        def __init__(self, con):
            self.con = con

        def execute(self, sql, *a, **k):
            statements.append(sql)
            return self.con.execute(sql, *a, **k)

        def close(self):
            self.con.close()

    def spying_connect(*args, **kwargs):
        return Spy(real_connect(*args, **kwargs))

    monkeypatch.setattr(module, "connect", spying_connect)
    report = health(path, threshold=3)
    assert report["integrity"] == "not_checked" and report["status"] == "healthy"
    assert not any("integrity_check" in s or "quick_check" in s for s in statements)
    deep = health(path, threshold=3, deep=True)
    assert deep["integrity"] == "ok"
    assert any("integrity_check" in s for s in statements)
