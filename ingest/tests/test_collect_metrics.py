import itertools
import json

import pytest

from news_ingest.cli import main
from news_ingest.config import load_config
from news_ingest.db import Database
from news_ingest.http import FetchResult


@pytest.mark.parametrize("mode", ["success", "not_modified", "failed", "partial", "rollback"])
def test_collect_cli_metrics_offline(mode, tmp_path, config_path, monkeypatch, capsys):
    database = tmp_path / "var" / "news.sqlite3"
    config = tmp_path / "config" / "sources.yaml"
    config.parent.mkdir()
    config.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {database}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {tmp_path / 'news.lock'}")
    )
    feeds = load_config(config).sources["bbc"].feeds
    first_url = str(feeds[0].url)
    body = (
        b'<rss version="2.0"><channel><title>Test</title><item><title>News</title>'
        b"<link>https://www.bbc.co.uk/news/articles/example</link><guid>example</guid>"
        b"<pubDate>Mon, 14 Sep 2026 03:38:13 GMT</pubDate></item></channel></rss>"
    )
    db = Database(database)
    if mode == "rollback":
        db.con.execute(
            "CREATE TRIGGER reject_article BEFORE INSERT ON articles "
            "BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
        )
        db.con.commit()
    db.close()

    async def fake_fetch(client, url, state, http_config, max_bytes):
        if mode == "failed" or (mode == "partial" and url != first_url):
            raise RuntimeError("simulated upstream failure")
        status = 304 if mode == "not_modified" or url != first_url else 200
        return FetchResult(status, body if status == 200 else b"", 1, url, None, None, [])

    monkeypatch.setattr("news_ingest.collect.fetch", fake_fetch)
    clock = itertools.count()
    monkeypatch.setattr("news_ingest.collect.perf_counter", lambda: next(clock) / 10)
    for iteration in (1, 2):
        code = main(["collect", "--config", str(config), "--source", "bbc", "--once"])
        envelope = json.loads(capsys.readouterr().out)
        result = envelope["result"] if code == 0 else envelope["error"]["details"]
        expected = 1 if mode in ("success", "partial") else 0
        assert result["sightings_inserted"] == expected
        assert result["historical_rows_read"] == expected
        assert result["merge_state_rows_read"] == (iteration - 1) * expected
        assert result["merge_state_bootstraps"] == (2 - iteration) * expected
        assert set(result["timings_seconds"]) == {"fetch", "parse", "database", "total"}
        assert all(value >= 0 for value in result["timings_seconds"].values())
        assert result["timings_seconds"]["total"] >= sum(
            result["timings_seconds"][key] for key in ("fetch", "parse", "database")
        )
    db = Database(database)
    try:
        assert db.con.execute("SELECT count(*) FROM sightings").fetchone()[0] == 2 * expected
        assert db.con.execute("SELECT count(*) FROM article_versions").fetchone()[0] == expected
        assert db.con.execute("SELECT count(*) FROM sighting_contents").fetchone()[0] == expected
        summary = db.con.execute(
            "SELECT summary_json FROM fetch_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        assert json.loads(summary)["timings_seconds"] == result["timings_seconds"]
        # The run row records the database's used bytes for `health`; the result does not.
        assert json.loads(summary)["database_used_bytes"] > 0
        assert "database_used_bytes" not in result
        assert db.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        db.close()
