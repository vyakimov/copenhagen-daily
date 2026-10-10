import json
from datetime import UTC, datetime, timedelta

from news_ingest.cli import main
from news_ingest.collect import process_lock
from news_ingest.config import load_config
from news_ingest.db import Database
from news_ingest.hashing import content_hash
from news_ingest.models import ArticleSnapshot

BASE = datetime(2026, 10, 1, tzinfo=UTC)


def snapshot(source_id, minute, title="Headline", feed="wsj.world", mod="rss_world", **values):
    article = ArticleSnapshot(
        source="wsj",
        source_id=source_id,
        title=title,
        raw_url=f"https://www.wsj.com/a?mod={mod}",
        canonical_url=f"https://www.wsj.com/a?mod={mod}",
        description="Same",
        description_source=feed,
        published_at=BASE,
        timestamp_original=BASE.isoformat(),
        first_seen_at=BASE,
        last_seen_at=BASE + timedelta(minutes=minute),
        last_checked_at=BASE + timedelta(minutes=minute),
        **values,
    )
    return article.model_copy(update={"content_hash": content_hash(article)})


def setup(tmp_path, config_path):
    config_file = tmp_path / "config" / "sources.yaml"
    config_file.parent.mkdir()
    config_file.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {tmp_path / 'db'}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {tmp_path / 'lock'}")
    )
    config = load_config(config_file)
    db = Database(config.database_path)
    # Versions as the old merge wrote them: provenance and WSJ `mod` rotate between feeds.
    history = {
        "rotating": [
            snapshot("rotating", 0),
            snapshot("rotating", 1, feed="wsj.opinion", mod="rss_opinion"),
            snapshot("rotating", 2),
            snapshot("rotating", 3, title="Edited"),
            snapshot("rotating", 4, title="Edited", feed="wsj.opinion"),
            snapshot("rotating", 5),
        ],
        "variants": [
            snapshot("variants", 0, title="Opinion | X"),
            snapshot("variants", 1, title="X", feed="wsj.opinion"),
            snapshot("variants", 2, title="Opinion | X"),
        ],
    }
    for source_id, versions in history.items():
        latest = versions[-1]
        db.con.execute(
            "INSERT INTO articles(source,source_id,snapshot_json,published_at,last_changed_at,"
            "content_hash) VALUES('wsj',?,?,?,?,?)",
            (source_id, latest.model_dump_json(), "2026-10-01T00:00:00.000000Z", "x", "x"),
        )
        for version in versions:
            db.con.execute(
                "INSERT INTO article_versions(source,source_id,content_hash,observed_at,snapshot_json) "
                "VALUES('wsj',?,?,?,?)",
                (
                    source_id,
                    version.content_hash,
                    version.last_seen_at.isoformat(),
                    version.model_dump_json(),
                ),
            )
    db.con.commit()
    return db, config_file, config


def titles(db, source_id):
    rows = db.con.execute(
        "SELECT snapshot_json FROM article_versions WHERE source_id=? ORDER BY version_id",
        (source_id,),
    )
    return [json.loads(row[0])["title"] for row in rows]


def run(capsys, config_file, *args):
    code = main(["collapse-versions", "--config", str(config_file), *args])
    return code, json.loads(capsys.readouterr().out)


def test_only_repeats_under_the_content_rule_are_removed(tmp_path, config_path, capsys):
    db, config_file, _ = setup(tmp_path, config_path)
    code, preview = run(capsys, config_file, "--dry-run")
    assert code == 0
    assert preview["result"]["redundant"] == 3
    assert titles(db, "rotating") == ["Headline"] * 3 + ["Edited"] * 2 + ["Headline"]
    code, applied = run(capsys, config_file)
    assert code == 0
    assert applied["result"] == {**preview["result"], "dry_run": False}
    # Provenance and `mod` rotations go; the edit and the change back stay, in order.
    assert titles(db, "rotating") == ["Headline", "Edited", "Headline"]
    # Different titles are different content, whichever feed showed them.
    assert titles(db, "variants") == ["Opinion | X", "X", "Opinion | X"]
    assert run(capsys, config_file)[1]["result"]["redundant"] == 0
    assert db.con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_collapse_respects_the_process_lock(tmp_path, config_path, capsys):
    db, config_file, config = setup(tmp_path, config_path)
    with process_lock(config.lock_path):
        code, envelope = run(capsys, config_file)
        assert code == 1
        assert envelope["error"]["type"] == "lock_busy"
    assert len(titles(db, "rotating")) == 6
