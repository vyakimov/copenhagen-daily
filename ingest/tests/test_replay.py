import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from news_ingest.cli import main
from news_ingest.collect import process_lock
from news_ingest.config import load_config
from news_ingest.db import Database, has_sighting_content, migrate, read_sightings
from news_ingest.feed import ParsedFeed, SightingCandidate
from news_ingest.http import FetchResult
from news_ingest.models import ArticleSnapshot


@pytest.fixture
def history(tmp_path, config_path, monkeypatch):
    path = tmp_path / "var" / "news.sqlite3"
    config_file = tmp_path / "config" / "sources.yaml"
    config_file.parent.mkdir()
    config_file.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {path}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {tmp_path / 'news.lock'}")
    )
    config = load_config(config_file)
    db = Database(path)
    priorities = {
        feed.id: (feed.description_priority, feed.order)
        for source in config.sources.values()
        for feed in source.feeds
    }
    run = db.start_run()
    base = datetime(2026, 9, 29, tzinfo=UTC)
    observations = [
        ("bbc", 0, "A", "original", ["old"]),
        ("bbc", 0, "A", "original", ["old"]),
        ("bbc", 0, "B", "short", ["new"]),
        ("bbc", 0, "A", "original", ["old", "new"]),
        ("dr", 0, "Latest", "latest description", ["latest"]),
        ("dr", 1, "Section", "section description", ["section"]),
        ("dr", 0, "New latest", "new latest description", []),
        ("dr", 1, "Section corrected", None, []),
    ]
    for index, (sid, feed_index, title, description, categories) in enumerate(observations):
        observed = base + timedelta(minutes=index)
        monkeypatch.setattr("news_ingest.db.now_utc", lambda value=observed: value)
        feed = config.sources[sid].feeds[feed_index]
        article = ArticleSnapshot(
            source=sid,
            source_id="example",
            title=title,
            raw_url=f"https://example.com/{sid}",
            canonical_url=f"https://example.com/{sid}",
            published_at=base,
            timestamp_original=base.isoformat(),
            first_seen_at=observed,
            last_seen_at=observed,
            last_checked_at=observed,
            description=description,
            description_source=feed.id,
            categories=categories,
            keywords=categories,
            authors=["Writer", "Writer"],
            raw_metadata={"title": title},
        )
        candidate = SightingCandidate(article, feed.id, 1, None, {"title": title})
        parsed = ParsedFeed([candidate], [], 1, 1, [], None)
        reply = FetchResult(200, title.encode(), 1, str(feed.url), None, None, [])
        poll = db.preallocate_poll(run, feed.id, sid, None)
        db.ingest(poll, feed.id, sid, str(feed.url), reply, parsed, priorities, feed.surface)
    yield db, config_file, config
    db.close()


def invoke(capsys, config_file, *args):
    code = main(["rebuild-articles", "--config", str(config_file), *args])
    result = json.loads(capsys.readouterr().out)
    return code, result


def dump(db, table):
    return [tuple(row) for row in db.con.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def test_clean_rebuild_is_exact_and_preserves_history(history, capsys):
    db, config_file, _ = history
    tables = (
        "articles",
        "sightings",
        "article_versions",
        "appearances",
        "raw_payloads",
        "feed_state",
        "feed_polls",
        "fetch_runs",
        "schema_migrations",
    )
    before = {table: dump(db, table) for table in tables}
    for args in (("--dry-run",), (), ("--dry-run",)):
        code, envelope = invoke(capsys, config_file, *args)
        assert code == 0
        result = envelope["result"]
        assert (result["rows_added"], result["rows_removed"], result["rows_changed"]) == (0, 0, 0)
        assert result["article_count"] == 2
        assert result["sightings_read"] == 8
        assert list(result["by_source"]) == ["bbc", "dr"]
        assert {table: dump(db, table) for table in tables} == before


def test_rebuild_repairs_without_versions_and_restores_change_time(history, capsys):
    db, config_file, _ = history
    expected = dump(db, "articles")
    versions = dump(db, "article_versions")
    db.con.execute("UPDATE articles SET content_hash='broken',last_changed_at='broken'")
    db.con.commit()
    corrupt = dump(db, "articles")
    code, preview = invoke(capsys, config_file, "--dry-run")
    assert code == 0
    assert preview["result"]["rows_changed"] == 2
    assert dump(db, "articles") == corrupt
    code, applied = invoke(capsys, config_file)
    assert code == 0
    assert applied["result"]["rows_changed"] == 2
    assert dump(db, "articles") == expected
    assert dump(db, "article_versions") == versions
    assert db.con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_filter_isolates_repair_and_validation(history, capsys):
    db, config_file, _ = history
    expected = dump(db, "articles")[0]
    db.con.execute("UPDATE articles SET content_hash='broken'")
    db.con.execute(
        "UPDATE sighting_contents SET normalized_template=json_set(normalized_template,'$.title',NULL) "
        "WHERE content_id IN (SELECT content_id FROM sightings WHERE source='dr')"
    )
    db.con.commit()
    dr_before = tuple(db.con.execute("SELECT * FROM articles WHERE source='dr'").fetchone())
    code, envelope = invoke(capsys, config_file, "--source", "bbc")
    assert code == 0
    assert envelope["result"]["rows_changed"] == 1
    assert list(envelope["result"]["by_source"]) == ["bbc"]
    assert tuple(db.con.execute("SELECT * FROM articles WHERE source='bbc'").fetchone()) == expected
    assert tuple(db.con.execute("SELECT * FROM articles WHERE source='dr'").fetchone()) == dr_before


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("defect", ["invalid", "identity", "unknown_feed"])
def test_invalid_history_leaves_projection_untouched(history, capsys, dry_run, defect):
    db, config_file, _ = history
    if defect == "invalid":
        db.con.execute(
            "UPDATE sighting_contents SET normalized_template=json_set(normalized_template,'$.title',NULL) "
            "WHERE content_id IN (SELECT content_id FROM sightings WHERE source='dr')"
        )
    elif defect == "identity":
        db.con.execute("UPDATE sightings SET source_id='mismatch' WHERE source='dr'")
    else:
        db.con.execute("UPDATE sightings SET feed_id='retired.unknown' WHERE source='dr'")
    db.con.execute("UPDATE articles SET content_hash='broken'")
    db.con.commit()
    before = dump(db, "articles")
    code, envelope = invoke(capsys, config_file, *(["--dry-run"] if dry_run else []))
    assert code == 1
    assert envelope["error"]["type"] == (
        "rebuild_unknown_feed" if defect == "unknown_feed" else "rebuild_invalid_sighting"
    )
    assert dump(db, "articles") == before


def test_apply_failure_rolls_back_earlier_updates(history, capsys):
    db, config_file, _ = history
    db.con.execute("UPDATE articles SET content_hash='broken'")
    db.con.execute(
        "CREATE TRIGGER fail_rebuild BEFORE UPDATE ON articles WHEN NEW.source='dr' "
        "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
    )
    db.con.commit()
    before = dump(db, "articles")
    code, _ = invoke(capsys, config_file)
    assert code == 1
    assert dump(db, "articles") == before


def test_rebuild_respects_process_lock(history, capsys):
    db, config_file, config = history
    before = dump(db, "articles")
    with process_lock(config.lock_path):
        code, envelope = invoke(capsys, config_file)
        assert code == 1
        assert envelope["error"]["type"] == "lock_busy"
        # A read-only preview can run while the process lock is held.
        assert invoke(capsys, config_file, "--dry-run")[0] == 0
    assert dump(db, "articles") == before


def test_missing_projection_and_unreferenced_extras_are_reconciled(history, capsys):
    db, config_file, _ = history
    expected = db.con.execute("SELECT snapshot_json FROM articles WHERE source='bbc'").fetchone()[0]
    # Simulate a damaged projection while retaining version evidence for the missing row.
    db.con.execute("PRAGMA foreign_keys=OFF")
    db.con.execute("DELETE FROM articles WHERE source='bbc'")
    db.con.execute(
        "INSERT INTO articles(source,source_id,snapshot_json,published_at,last_changed_at,content_hash) "
        "VALUES('bbc','extra','{}','2026-09-29T00:00:00.000000Z','2026-09-29T00:00:00.000000Z','extra')"
    )
    db.con.commit()
    db.con.execute("PRAGMA foreign_keys=ON")
    versions = dump(db, "article_versions")
    for args in (("--dry-run",), ()):
        code, envelope = invoke(capsys, config_file, *args)
        assert code == 0
        assert envelope["result"]["rows_added"] == 1
        assert envelope["result"]["rows_removed"] == 1
    assert (
        db.con.execute("SELECT snapshot_json FROM articles WHERE source='bbc'").fetchone()[0]
        == expected
    )
    assert dump(db, "article_versions") == versions
    assert db.con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_removal_cannot_destroy_historical_versions(history, capsys):
    db, config_file, _ = history
    db.con.execute("DELETE FROM sightings WHERE source='bbc'")
    db.con.commit()
    before = dump(db, "articles")
    versions = dump(db, "article_versions")
    code, envelope = invoke(capsys, config_file, "--dry-run")
    assert code == 0
    assert envelope["result"]["rows_removed"] == envelope["result"]["blocked_removals"] == 1
    code, envelope = invoke(capsys, config_file)
    assert code == 1
    assert envelope["error"]["type"] == "rebuild_conflict"
    assert dump(db, "articles") == before
    assert dump(db, "article_versions") == versions


def test_wrapper_rebuild_smoke_uses_temporary_database(history, tmp_path):
    db, config_file, _ = history
    root = Path(__file__).parents[1]

    def export(name):
        output = tmp_path / name
        completed = subprocess.run(
            [
                str(root / "gather_news.sh"),
                "export",
                "--config",
                str(config_file),
                "--since",
                "2026-09-29T00:00:00Z",
                "--until",
                "2026-09-30T00:00:00Z",
                "--output",
                str(output),
            ],
            cwd="/tmp",
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout
        return [(output / name).read_bytes() for name in ("articles.jsonl", "appearances.jsonl")]

    before = export("before")
    db.con.execute("UPDATE articles SET content_hash='broken'")
    db.con.commit()
    for args, changed in ((["--dry-run"], 2), ([], 2), (["--dry-run"], 0)):
        completed = subprocess.run(
            [str(root / "gather_news.sh"), "rebuild-articles", "--config", str(config_file), *args],
            cwd="/tmp",
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout
        assert json.loads(completed.stdout)["result"]["rows_changed"] == changed
    assert export("after") == before


def test_disabled_source_remains_rebuildable(history, capsys):
    _, config_file, config = history
    import yaml

    config.sources["bbc"].enabled = False
    config_file.write_text(yaml.safe_dump(config.model_dump(mode="json")))
    code, envelope = invoke(capsys, config_file, "--source", "bbc", "--dry-run")
    assert code == 0
    assert envelope["result"]["article_count"] == 1
    assert envelope["result"]["rows_changed"] == 0


def repeat_observation(db, config, monkeypatch, title="Next"):
    latest = list(read_sightings(db.con, source="bbc"))[-1]
    article = ArticleSnapshot.model_validate_json(latest["normalized_json"])
    observed = article.last_seen_at + timedelta(minutes=1)
    article = article.model_copy(
        update={
            "title": title,
            "first_seen_at": observed,
            "last_seen_at": observed,
            "last_checked_at": observed,
        }
    )
    monkeypatch.setattr("news_ingest.db.now_utc", lambda: observed)
    feed = config.sources["bbc"].feeds[0]
    run = db.start_run("bbc")
    poll = db.preallocate_poll(run, feed.id, "bbc", None)
    parsed = ParsedFeed([SightingCandidate(article, feed.id, 1, None, {})], [], 1, 1, [], None)
    reply = FetchResult(200, title.encode(), 1, str(feed.url), "new-etag", None, [])
    priorities = {
        f.id: (f.description_priority, f.order) for sc in config.sources.values() for f in sc.feeds
    }
    return db.ingest(poll, feed.id, "bbc", str(feed.url), reply, parsed, priorities, feed.surface)


def test_persistent_state_survives_restart_and_matches_rebuild(history, capsys, monkeypatch):
    db, config_file, config = history
    restarted = Database(db.path)
    try:
        for title in ("A", "B", "A", "A"):
            metrics = repeat_observation(restarted, config, monkeypatch, title)
            assert metrics["historical_rows_read"] == 1
            assert metrics["merge_state_rows_read"] == 1
            assert metrics["merge_state_bootstraps"] == 0
            code, envelope = invoke(capsys, config_file, "--dry-run")
            assert code == 0
            assert envelope["result"]["rows_changed"] == 0
    finally:
        restarted.close()


@pytest.mark.parametrize("damage", ["missing_head", "missing_state", "invalid_state"])
def test_cache_bootstraps_once_from_history(history, capsys, monkeypatch, damage):
    db, config_file, config = history
    if damage == "missing_head":
        db.con.execute("DELETE FROM article_merge_heads WHERE source='bbc'")
    elif damage == "missing_state":
        db.con.execute("DELETE FROM article_feed_merge_state WHERE source='bbc'")
    else:
        db.con.execute("UPDATE article_feed_merge_state SET state_json='{}' WHERE source='bbc'")
    db.con.commit()
    metrics = repeat_observation(db, config, monkeypatch)
    assert metrics["historical_rows_read"] == 5
    assert metrics["merge_state_bootstraps"] == 1
    metrics = repeat_observation(db, config, monkeypatch)
    assert metrics["historical_rows_read"] == 1
    assert metrics["merge_state_bootstraps"] == 0
    code, envelope = invoke(capsys, config_file, "--dry-run")
    assert code == 0
    assert envelope["result"]["rows_changed"] == 0


def test_cache_and_watermark_roll_back_with_failed_feed(history, monkeypatch):
    import sqlite3

    db, _, config = history
    tables = (
        "article_feed_merge_state",
        "article_merge_heads",
        "sighting_contents",
        "sightings",
        "articles",
        "article_versions",
        "raw_payloads",
        "appearances",
        "feed_state",
    )
    before = {table: dump(db, table) for table in tables}
    db.con.execute(
        "CREATE TRIGGER reject_projection BEFORE INSERT ON articles "
        "BEGIN SELECT RAISE(ABORT, 'simulated failure after cache update'); END"
    )
    db.con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        repeat_observation(db, config, monkeypatch)
    assert {table: dump(db, table) for table in tables} == before
    db.con.execute("DROP TRIGGER reject_projection")
    db.con.commit()
    assert repeat_observation(db, config, monkeypatch)["historical_rows_read"] == 1


def test_rebuild_repairs_cache_only_and_respects_source_scope(history, capsys, monkeypatch):
    db, config_file, config = history
    dr_state = tuple(
        db.con.execute("SELECT * FROM article_merge_heads WHERE source='dr'").fetchone()
    )
    db.con.execute("DELETE FROM article_feed_merge_state WHERE source='bbc'")
    db.con.execute("DELETE FROM article_merge_heads WHERE source='bbc'")
    db.con.commit()
    for args in (("--source", "bbc", "--dry-run"), ("--source", "bbc")):
        code, envelope = invoke(capsys, config_file, *args)
        assert code == 0
        assert envelope["result"]["rows_changed"] == 0
        assert envelope["result"]["merge_states_rebuilt"] == 1
        if "--dry-run" in args:
            assert (
                db.con.execute(
                    "SELECT count(*) FROM article_merge_heads WHERE source='bbc'"
                ).fetchone()[0]
                == 0
            )
    assert (
        tuple(db.con.execute("SELECT * FROM article_merge_heads WHERE source='dr'").fetchone())
        == dr_state
    )
    assert repeat_observation(db, config, monkeypatch)["historical_rows_read"] == 1


def test_upgrade_initializes_cache_without_rewriting_history(history, capsys, monkeypatch):
    db, config_file, config = history
    tables = ("sightings", "articles", "article_versions", "appearances", "raw_payloads")
    before = {table: dump(db, table) for table in tables}
    db.con.execute("DROP TABLE article_feed_merge_state")
    db.con.execute("DROP TABLE article_merge_heads")
    db.con.execute("DELETE FROM schema_migrations WHERE version=4")
    db.con.commit()
    # Preview on an older schema must not apply migrations or populate persistent state.
    assert invoke(capsys, config_file, "--dry-run")[0] == 0
    assert db.con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 4
    upgraded = Database(db.path)
    try:
        assert {table: dump(upgraded, table) for table in tables} == before
        assert upgraded.con.execute("SELECT count(*) FROM article_merge_heads").fetchone()[0] == 0
        assert repeat_observation(upgraded, config, monkeypatch)["historical_rows_read"] == 5
        assert repeat_observation(upgraded, config, monkeypatch)["historical_rows_read"] == 1
    finally:
        upgraded.close()
    assert invoke(capsys, config_file, "--dry-run")[1]["result"]["rows_changed"] == 0


@pytest.fixture
def legacy_history(history):
    db, config_file, config = history
    rows = list(read_sightings(db.con, include_raw=True))
    db.con.execute("DROP TABLE sightings")
    db.con.execute("DROP TABLE sighting_contents")
    schema = (Path(__file__).parents[1] / "migrations" / "001_initial.sql").read_text()
    db.con.execute(
        next(line for line in schema.splitlines() if line.startswith("CREATE TABLE sightings("))
    )
    db.con.execute("CREATE INDEX sightings_article_idx ON sightings(source,source_id)")
    columns = (
        "sighting_id",
        "poll_id",
        "feed_id",
        "source",
        "source_id",
        "item_position",
        "publisher_order",
        "observed_at",
        "normalized_json",
        "raw_metadata_json",
        "raw_item_json",
    )
    db.con.executemany(
        "INSERT INTO sightings VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [tuple(row[column] for column in columns) for row in rows],
    )
    db.con.execute("DELETE FROM schema_migrations WHERE version=5")
    db.con.commit()
    db.compact_sightings = False
    return db, config_file, config


def test_content_migration_roundtrip_is_atomic_and_idempotent(legacy_history, monkeypatch, capsys):
    db, config_file, config = legacy_history
    before = list(read_sightings(db.con, include_raw=True))
    tables = (
        "articles",
        "article_versions",
        "raw_payloads",
        "appearances",
        "feed_state",
        "article_merge_heads",
        "article_feed_merge_state",
    )
    facts = {table: dump(db, table) for table in tables}
    migrate(db.con)
    assert not has_sighting_content(db.con)  # Collection never auto-migrates populated history.
    db.con.execute("UPDATE sqlite_sequence SET seq=9000 WHERE name='sightings'")
    db.con.commit()
    migrate(db.con, allow_content_migration=True)
    assert list(read_sightings(db.con, include_raw=True)) == before
    assert {table: dump(db, table) for table in tables} == facts
    assert db.con.execute("SELECT count(*) FROM sighting_contents").fetchone()[0] < len(before)
    assert (
        db.con.execute("SELECT seq FROM sqlite_sequence WHERE name='sightings'").fetchone()[0]
        == 9000
    )
    migrate(db.con, allow_content_migration=True)
    assert list(read_sightings(db.con, include_raw=True)) == before
    assert invoke(capsys, config_file, "--dry-run")[1]["result"]["rows_changed"] == 0
    restarted = Database(db.path)
    try:
        repeat_observation(restarted, config, monkeypatch)
        assert restarted.con.execute("SELECT max(sighting_id) FROM sightings").fetchone()[0] == 9001
        assert restarted.con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restarted.close()


def test_content_migration_failure_after_swap_restores_legacy_tables(legacy_history):
    import sqlite3

    db, _, _ = legacy_history
    before = list(read_sightings(db.con, include_raw=True))
    db.con.execute(
        "CREATE TRIGGER reject_migration BEFORE INSERT ON schema_migrations WHEN NEW.version=5 "
        "BEGIN SELECT RAISE(ABORT, 'failure after table swap'); END"
    )
    db.con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        migrate(db.con, allow_content_migration=True)
    assert not has_sighting_content(db.con)
    assert list(read_sightings(db.con, include_raw=True)) == before
    assert db.con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 4
    assert not db.con.execute(
        "SELECT 1 FROM sqlite_master WHERE name IN ('sighting_contents','sightings_v5')"
    ).fetchone()


def test_repeated_content_reuses_blob_and_preserves_a_b_a_versions(history, monkeypatch):
    db, _, config = history
    versions = db.con.execute("SELECT count(*) FROM article_versions").fetchone()[0]
    content_counts = []
    for title in ("A", "B", "A", "A"):
        repeat_observation(db, config, monkeypatch, title)
        content_counts.append(
            db.con.execute("SELECT count(*) FROM sighting_contents").fetchone()[0]
        )
    assert content_counts[1] == content_counts[0] + 1
    assert content_counts[2:] == [content_counts[1], content_counts[1]]
    assert db.con.execute("SELECT count(*) FROM article_versions").fetchone()[0] == versions + 2


def test_storage_digest_collision_rolls_back_instead_of_sharing_wrong_content(history, monkeypatch):
    from news_ingest.db import store_sighting_content

    db, _, _ = history
    before = dump(db, "sighting_contents")
    row = next(read_sightings(db.con, source="bbc", include_raw=True))
    changed = json.loads(row["normalized_json"])
    changed["title"] = "Different content"
    monkeypatch.setattr(
        "news_ingest.sighting_content.storage_digest", lambda *args: "forced-collision"
    )
    with pytest.raises(ValueError), db.con:
        for normalized in (row["normalized_json"], json.dumps(changed)):
            store_sighting_content(
                db.con, "bbc", "example", normalized, row["raw_metadata_json"], row["raw_item_json"]
            )
    assert dump(db, "sighting_contents") == before


def test_dedup_cli_requires_backup_and_lock_and_preserves_exports(legacy_history, tmp_path, capsys):
    db, config_file, config = legacy_history
    root = Path(__file__).parents[1]
    before = list(read_sightings(db.con, include_raw=True))
    argv = ["deduplicate-sightings", "--config", str(config_file)]
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "invalid_arguments"
    backup_path = tmp_path / "before-dedup.sqlite3"
    with process_lock(config.lock_path):
        assert main([*argv, "--backup", str(backup_path)]) == 1
        assert json.loads(capsys.readouterr().out)["error"]["type"] == "lock_busy"
        assert not backup_path.exists()
    exports = []
    for name in ("before", "after"):
        output = tmp_path / f"dedup-{name}"
        code = main(
            [
                "export",
                "--config",
                str(config_file),
                "--since",
                "2026-09-29T00:00:00Z",
                "--until",
                "2026-09-30T00:00:00Z",
                "--output",
                str(output),
            ]
        )
        assert code == 0
        capsys.readouterr()
        exports.append(
            [
                (output / filename).read_bytes()
                for filename in ("articles.jsonl", "appearances.jsonl")
            ]
        )
        if name == "before":
            result = subprocess.run(
                [str(root / "gather_news.sh"), *argv, "--backup", str(backup_path)],
                cwd="/tmp",
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, result.stdout
            assert json.loads(result.stdout)["result"]["migrated"] is True
    assert exports[0] == exports[1]
    assert list(read_sightings(db.con, include_raw=True)) == before
    from news_ingest.db import connect

    saved = connect(backup_path, readonly=True)
    try:
        assert not has_sighting_content(saved)
        assert list(read_sightings(saved, include_raw=True)) == before
    finally:
        saved.close()
