"""Disposable collection benchmark; run through gather_news.sh benchmark-collect.

Fixture construction and diagnostic SQL here operate only on temporary databases.
Production persistence remains in news_ingest.db.
"""

from __future__ import annotations

from pathlib import Path

from news_ingest.db import Database


def benchmark_collect():
    """Compare ingestion on identical disposable histories; never open the live database."""
    from datetime import UTC, datetime
    from tempfile import TemporaryDirectory
    from time import perf_counter

    from news_ingest.config import FeedConfig, SourceConfig
    from news_ingest.feed import parse_feed
    from news_ingest.http import FetchResult

    feed = FeedConfig(
        id="benchmark",
        name="Benchmark",
        url="https://example.com/rss",
        surface="latest_rss",
        order=0,
        description_priority=10,
    )
    source = SourceConfig(enabled=True, identity="guid", feeds=[feed])

    def response(size):
        return (
            '<rss version="2.0"><channel><title>Benchmark</title>'
            + "".join(
                f"<item><guid>article-{i}</guid><title>Article {i}</title>"
                f"<link>https://example.com/{i}</link><description>{'x' * 2500}</description>"
                "<pubDate>Mon, 14 Sep 2026 03:38:13 GMT</pubDate></item>"
                for i in range(size)
            )
            + "</channel></rss>"
        ).encode()

    def ingest(db, poll, body):
        parsed = parse_feed(body, feed, datetime(2026, 9, 29, tzinfo=UTC), "benchmark", source)
        reply = FetchResult(200, body, 1, str(feed.url), None, None, [])
        return db.ingest(
            poll, feed.id, "benchmark", str(feed.url), reply, parsed, {feed.id: (10, 0)}
        )

    with TemporaryDirectory(prefix="news-ingest-benchmark-") as directory:
        seed = Database(Path(directory) / "seed.sqlite3")
        try:
            run = seed.start_run("benchmark")
            first = seed.preallocate_poll(run, feed.id, "benchmark", None)
            ingest(seed, first, response(500))
            # Replicate retained observations cheaply; the measured path is real ingestion.
            for _ in range(19):
                poll = seed.preallocate_poll(run, feed.id, "benchmark", None)
                with seed.con:
                    seed.con.execute(
                        "INSERT INTO sightings(poll_id,feed_id,source,source_id,item_position,"
                        "publisher_order,observed_at,content_id,observation_json) "
                        "SELECT ?,feed_id,source,source_id,item_position,publisher_order,observed_at,"
                        "content_id,observation_json FROM sightings WHERE poll_id=?",
                        (poll, first),
                    )
            measurements = {}
            outputs = []
            body = response(20)
            with seed.con:
                seed.con.execute("DELETE FROM article_feed_merge_state")
                seed.con.execute("DELETE FROM article_merge_heads")
            for label in ("unindexed", "indexed", "cached"):
                db = Database(Path(directory) / f"{label}.sqlite3")
                try:
                    seed.con.backup(db.con)
                    if label == "unindexed":
                        db.con.execute("DROP INDEX sightings_article_idx")
                        db.con.commit()
                    if label == "cached":
                        with db.con:
                            for index in range(20):
                                db.merge_article(
                                    "benchmark", f"article-{index}", {feed.id: (10, 0)}
                                )
                    plan = [
                        row[3]
                        for row in db.con.execute(
                            "EXPLAIN QUERY PLAN SELECT content_id,feed_id,item_position,"
                            "publisher_order FROM sightings WHERE source=? AND source_id=? "
                            "AND sighting_id>? "
                            "ORDER BY sighting_id",
                            ("benchmark", "article-0", 0),
                        )
                    ]
                    trial = db.preallocate_poll(run, feed.id, "benchmark", None)
                    started = perf_counter()
                    counts = ingest(db, trial, body)
                    measurements[label] = {
                        "parse_and_ingest_seconds": round(perf_counter() - started, 6),
                        "query_plan": plan,
                        **counts,
                    }
                    outputs.append(
                        [
                            tuple(row)
                            for row in db.con.execute(
                                "SELECT source,source_id,snapshot_json FROM articles "
                                "ORDER BY source,source_id"
                            )
                        ]
                    )
                finally:
                    db.close()
            if any(output != outputs[0] for output in outputs[1:]):
                raise RuntimeError("benchmark projection mismatch")
            return {
                "history_rows": 10000,
                "items_per_response": 20,
                "fixture": "synthetic RSS; 500 identities, 20 observations each",
                "projection_equal": True,
                "measurements": measurements,
            }
        finally:
            seed.close()
