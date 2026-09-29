import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from news_ingest.cli import main
from news_ingest.collect import process_lock
from news_ingest.config import load_config
from news_ingest.db import Database
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
    db.con.execute("UPDATE sightings SET normalized_json='{}' WHERE source='dr'")
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
        db.con.execute("UPDATE sightings SET normalized_json='{}' WHERE source='dr'")
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
