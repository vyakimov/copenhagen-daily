from news_ingest.db import Database


def test_migrations_are_idempotent(tmp_path):
    one = Database(tmp_path / "news.sqlite")
    assert one.con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
    one.close()
    two = Database(tmp_path / "news.sqlite")
    assert two.con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    two.close()


def test_repeated_item_in_one_snapshot_is_quarantined_not_fatal(tmp_path, config_path):
    from datetime import UTC, datetime

    from news_ingest.config import load_config
    from news_ingest.feed import parse_feed
    from news_ingest.http import FetchResult

    config = load_config(config_path)
    source = config.sources["bbc"]
    feed = source.feeds[0]
    item = (
        "<item><title>{t}</title>"
        "<link>https://www.bbc.co.uk/news/articles/cy5zg41dkqwo?at_medium=RSS</link>"
        '<guid isPermaLink="false">https://www.bbc.co.uk/news/articles/cy5zg41dkqwo#{n}</guid>'
        "<description>d</description><pubDate>Mon, 14 Sep 2026 03:38:13 GMT</pubDate></item>"
    )
    body = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        + item.format(t="First placement", n=1)
        + item.format(t="Repeated placement", n=0)
        + "</channel></rss>"
    ).encode()
    parsed = parse_feed(body, feed, datetime.now(UTC), "bbc", source)
    assert len(parsed.entries) == 2
    db = Database(tmp_path / "news.sqlite")
    try:
        run = db.start_run("bbc")
        poll = db.preallocate_poll(run, feed.id, "bbc", db.state(feed.id))
        result = FetchResult(200, body, 1, str(feed.url), None, None, [])
        db.ingest(poll, feed.id, "bbc", str(feed.url), result, parsed, {feed.id: (10, 0)})
        rows = db.con.execute(
            "SELECT source_id, item_position FROM sightings WHERE poll_id=?", (poll,)
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [("cy5zg41dkqwo", 1)]
        quarantined = db.con.execute(
            "SELECT error_code, item_position FROM quarantine WHERE poll_id=?", (poll,)
        ).fetchall()
        assert [(q[0], q[1]) for q in quarantined] == [("duplicate_in_snapshot", 2)]
        assert db.con.execute("SELECT count(*) FROM articles WHERE source='bbc'").fetchone()[0] == 1
    finally:
        db.close()
