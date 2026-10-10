import json
from datetime import UTC, datetime, timedelta

import pytest

from news_ingest import payload_archive
from news_ingest.cli import main
from news_ingest.collect import process_lock
from news_ingest.config import load_config
from news_ingest.db import Database, read_raw_payload
from news_ingest.feed import ParsedFeed, SightingCandidate
from news_ingest.http import FetchResult
from news_ingest.models import ArticleSnapshot
from news_ingest.replay import backup

START = datetime(2026, 9, 20, tzinfo=UTC)
FEEDS = ("dr.latest", "dr.indland")


def test_archive_reproduces_every_body_and_rejects_tampering():
    bodies = [(payload_archive.body_hash(body), body) for body in (b"<rss>1</rss>", b"", b"x" * 99)]
    archive, members = payload_archive.pack(bodies)
    for (content_hash, body), (_, offset, length) in zip(bodies, members, strict=True):
        assert payload_archive.extract(archive, offset, length, content_hash) == body
    with pytest.raises(ValueError):
        payload_archive.verify(archive, members[:-1])
    with pytest.raises(ValueError):
        payload_archive.pack([("sha256:" + "0" * 64, b"mismatch")])


def make_config(tmp_path, config_path, name):
    root = tmp_path / name
    config_file = root / "config" / "sources.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        config_path.read_text()
        .replace(
            "database_path: var/news-ingest.sqlite3", f"database_path: {root / 'news.sqlite3'}"
        )
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {root / 'news.lock'}")
    )
    return config_file, load_config(config_file)


def poll(db, config, monkeypatch, feed_id, at, items, body=None, status=200):
    """Commit one poll of `feed_id` at `at`; items are (source_id, title[, parse time])."""
    feed = next(f for f in config.sources["dr"].feeds if f.id == feed_id)
    monkeypatch.setattr("news_ingest.db.now_utc", lambda: at)
    run = db.start_run("dr")
    poll_id = db.preallocate_poll(run, feed_id, "dr", None)
    if status == 304:
        db.commit_not_modified(poll_id, feed_id, "dr", str(feed.url))
        return
    if status != 200:
        db.fail_poll(poll_id, RuntimeError("upstream"), feed_id, "dr", str(feed.url))
        return
    entries = []
    for position, (source_id, title, *parsed_at) in enumerate(items, start=1):
        seen = parsed_at[0] if parsed_at else at
        article = ArticleSnapshot(
            source="dr",
            source_id=source_id,
            title=title,
            raw_url=f"https://www.dr.dk/{source_id}",
            canonical_url=f"https://www.dr.dk/{source_id}",
            description=f"{title} described",
            description_source=feed_id,
            published_at=START,
            timestamp_original=START.isoformat(),
            first_seen_at=seen,
            last_seen_at=seen,
            last_checked_at=seen,
        )
        entries.append(SightingCandidate(article, feed_id, position, None, {"title": title}))
    parsed = ParsedFeed(entries, [], len(entries), len(entries), [], None)
    body = body if body is not None else f"{feed_id} {at.isoformat()} {items}".encode()
    reply = FetchResult(200, body, 1, str(feed.url), None, None, [])
    priorities = {
        f.id: (f.description_priority, f.order) for sc in config.sources.values() for f in sc.feeds
    }
    db.ingest(poll_id, feed_id, "dr", str(feed.url), reply, parsed, priorities, feed.surface)


def schedule(hours):
    """What each feed shows at each hourly poll."""
    for hour in range(hours):
        at = START + timedelta(hours=hour)
        steady = ("steady", "Steady")
        edited = ("edited", "B" if 30 <= hour < 40 else "A")
        mover = [("mover", "Mover")] if hour % 50 != 25 else []  # absent from one poll
        latest = [steady, edited, *mover]
        if 60 <= hour < 70:
            latest = [edited, steady, *mover]  # positions swap for a while
        if hour == 80:
            latest.append(steady)  # listed twice in one snapshot
        yield "dr.latest", at, latest, 200
        status = 304 if hour % 7 == 3 else 500 if hour % 11 == 5 else 200
        yield "dr.indland", at + timedelta(seconds=30), [steady, ("section", "Section")], status


def export(capsys, config_file, tmp_path, name):
    output = tmp_path / f"export-{name}"
    args = ["export", "--config", str(config_file), "--since", "2026-09-01T00:00:00Z"]
    assert main([*args, "--until", "2026-11-01T00:00:00Z", "--output", str(output)]) == 0
    capsys.readouterr()
    return [(output / f).read_bytes() for f in ("articles.jsonl", "appearances.jsonl")]


def run(capsys, config_file, *args):
    code = main([args[0], "--config", str(config_file), *args[1:]])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def twins(tmp_path, config_path, monkeypatch):
    config_file, config = make_config(tmp_path, config_path, "compacted")
    db = Database(config.database_path)
    for feed_id, at, items, status in schedule(240):
        poll(db, config, monkeypatch, feed_id, at, items, status=status)
    # A body seen again later is stored once.
    poll(db, config, monkeypatch, "dr.indland", START + timedelta(hours=1, minutes=5), [], b"same")
    poll(db, config, monkeypatch, "dr.indland", START + timedelta(hours=2, minutes=5), [], b"same")
    db.close()
    twin_file, twin = make_config(tmp_path, config_path, "original")
    backup(config.database_path, twin.database_path)
    now = START + timedelta(hours=240)
    monkeypatch.setattr("news_ingest.time.now_utc", lambda: now)
    return config_file, config, twin_file, twin


def count(path, table):
    db = Database(path)
    try:
        return db.con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        db.close()


def test_compaction_preserves_exports_projection_and_every_body(
    twins, tmp_path, capsys, monkeypatch
):
    config_file, config, twin_file, twin = twins
    original = Database(twin.database_path)
    bodies = {
        row[0]: read_raw_payload(original.con, row[0])
        for row in original.con.execute("SELECT content_hash FROM raw_payloads")
    }
    original.close()
    before = {t: count(config.database_path, t) for t in ("sightings", "appearances")}

    code, preview = run(capsys, config_file, "compact-history", "--dry-run")
    assert code == 0
    assert {t: count(config.database_path, t) for t in before} == before
    code, applied = run(capsys, config_file, "compact-history")
    assert code == 0
    result = applied["result"]
    for key in ("sightings", "appearances"):
        assert result[key] == preview["result"][key]
        assert result[key]["rows_removed"] > 0
        assert count(config.database_path, key) == before[key] - result[key]["rows_removed"]
    assert result["payloads"]["bodies"] == preview["result"]["payloads"]["bodies"] > 0

    assert export(capsys, config_file, tmp_path, "compacted") == export(
        capsys, twin_file, tmp_path, "original"
    )
    code, rebuilt = run(capsys, config_file, "rebuild-articles", "--dry-run")
    assert code == 0
    assert rebuilt["result"]["rows_changed"] == 0
    compacted = Database(config.database_path)
    try:
        assert compacted.con.execute("SELECT count(*) FROM raw_payloads").fetchone()[0] < len(
            bodies
        )
        assert {h: read_raw_payload(compacted.con, h) for h in bodies} == bodies
        assert compacted.con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        compacted.close()

    # Running again finds nothing new to do, and VACUUM returns the freed pages.
    code, again = run(capsys, config_file, "compact-history", "--vacuum")
    assert code == 0, again
    assert again["result"]["vacuum_performed"] is True
    removed = result["sightings"]["rows_removed"]
    assert count(config.database_path, "sightings") == before["sightings"] - removed
    assert (
        again["result"]["sightings"]["rows_removed"],
        again["result"]["payloads"]["bodies"],
    ) == (0, 0)


def test_later_compaction_extends_runs_and_archived_bodies_are_not_stored_again(
    twins, tmp_path, capsys, monkeypatch
):
    config_file, config, twin_file, twin = twins
    assert run(capsys, config_file, "compact-history")[0] == 0
    archived = Database(config.database_path)
    known = archived.con.execute(
        "SELECT content_hash FROM raw_payload_members ORDER BY content_hash LIMIT 1"
    ).fetchone()[0]
    archived.close()
    more = START + timedelta(hours=240)
    for target in (config, twin):
        db = Database(target.database_path)
        for hour in range(48):
            at = more + timedelta(hours=hour)
            items = [("steady", "Steady"), ("edited", "A"), ("mover", "Mover")]
            poll(db, target, monkeypatch, "dr.latest", at, items)
        db.close()
    later = more + timedelta(days=9)
    monkeypatch.setattr("news_ingest.time.now_utc", lambda: later)
    code, applied = run(capsys, config_file, "compact-history")
    assert code == 0
    assert applied["result"]["sightings"]["rows_removed"] > 0
    assert export(capsys, config_file, tmp_path, "compacted") == export(
        capsys, twin_file, tmp_path, "original"
    )
    assert (
        run(capsys, config_file, "rebuild-articles", "--dry-run")[1]["result"]["rows_changed"] == 0
    )

    db = Database(config.database_path)
    try:
        body = read_raw_payload(db.con, known)
        before = db.con.execute("SELECT count(*) FROM raw_payloads").fetchone()[0]
        poll(db, config, monkeypatch, "dr.indland", later, [], body)
        assert db.con.execute("SELECT count(*) FROM raw_payloads").fetchone()[0] == before
    finally:
        db.close()


def test_compaction_respects_the_process_lock(twins, capsys):
    config_file, config, _, _ = twins
    before = count(config.database_path, "sightings")
    with process_lock(config.lock_path):
        code, envelope = run(capsys, config_file, "compact-history")
        assert code == 1
        assert envelope["error"]["type"] == "lock_busy"
        assert run(capsys, config_file, "compact-history", "--dry-run")[0] == 0
    assert count(config.database_path, "sightings") == before


def test_sightings_out_of_parse_time_order_are_kept(tmp_path, config_path, capsys, monkeypatch):
    """The merge orders a feed's sightings by parse time, so compaction may only fold sightings
    that arrived in that order; otherwise a removed interior could have been the winner."""
    config_file, config = make_config(tmp_path, config_path, "compacted")
    db = Database(config.database_path)
    clock = START.replace(hour=10)
    stories = {
        # A clock correction: the interior A holds the latest time, and B is older than it.
        "skewed": [("A", 0), ("A", 30), ("A", 15), ("B", 20)],
        # A is first parsed earlier than X, so it only starts winning at its second sighting.
        "late": [("X", 5), ("A", 0), ("A", 10), ("A", 20), ("A", 30)],
    }
    for hour in range(6):
        items = [("steady", "Steady")]
        for source_id, story in stories.items():
            if hour < len(story):
                title, minute = story[hour]
                items.append((source_id, title, clock + timedelta(minutes=minute)))
        poll(db, config, monkeypatch, "dr.latest", START + timedelta(hours=hour), items)
    db.close()
    twin_file, twin = make_config(tmp_path, config_path, "original")
    backup(config.database_path, twin.database_path)
    monkeypatch.setattr("news_ingest.time.now_utc", lambda: START + timedelta(days=30))

    code, applied = run(capsys, config_file, "compact-history")
    assert code == 0
    rebuilt = run(capsys, config_file, "rebuild-articles", "--dry-run")[1]["result"]
    assert rebuilt["rows_changed"] == 0
    assert export(capsys, config_file, tmp_path, "compacted") == export(
        capsys, twin_file, tmp_path, "original"
    )
    # Only "steady" (every interior) and the in-order tail of "late" are folded.
    assert applied["result"]["sightings"]["rows_removed"] == 4 + 1
