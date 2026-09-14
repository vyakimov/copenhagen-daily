from __future__ import annotations

import gzip
import json
import sqlite3
import uuid
from pathlib import Path

from .models import ArticleSnapshot
from .time import format_utc, now_utc


def connect(path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
    return con


def migrate(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    folder = Path(__file__).parents[2] / "migrations"
    for file in sorted(folder.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(file.name[:3])
        if not con.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
        ).fetchone():
            with con:
                con.executescript(file.read_text())
                con.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)", (version, format_utc(now_utc()))
                )


class Database:
    def __init__(self, path):
        self.path = path
        self.con = connect(path)
        migrate(self.con)

    def close(self):
        self.con.close()

    def start_run(self, source=None):
        run = str(uuid.uuid4())
        self.con.execute(
            "INSERT INTO fetch_runs(run_id,started_at,status,requested_source) VALUES(?,?,?,?)",
            (run, format_utc(now_utc()), "running", source),
        )
        self.con.commit()
        return run

    def finish_run(self, run, status, summary, warnings):
        self.con.execute(
            "UPDATE fetch_runs SET ended_at=?,status=?,summary_json=?,warnings_json=? WHERE run_id=?",
            (format_utc(now_utc()), status, json.dumps(summary), json.dumps(warnings), run),
        )
        self.con.commit()

    def state(self, feed_id):
        return self.con.execute("SELECT * FROM feed_state WHERE feed_id=?", (feed_id,)).fetchone()

    def preallocate_poll(self, run, feed_id, source, state):
        cur = self.con.execute(
            "INSERT INTO feed_polls(run_id,feed_id,source,started_at,status,sent_etag,sent_last_modified) VALUES(?,?,?,?,?,?,?)",
            (
                run,
                feed_id,
                source,
                format_utc(now_utc()),
                "running",
                state["etag"] if state else None,
                state["last_modified"] if state else None,
            ),
        )
        self.con.commit()
        return cur.lastrowid

    def fail_poll(self, poll, error):
        with self.con:
            self.con.execute(
                "UPDATE feed_polls SET status='failed',ended_at=?,error_json=? WHERE poll_id=?",
                (format_utc(now_utc()), json.dumps({"message": str(error)}), poll),
            )

    def commit_not_modified(self, poll, feed, source, url):
        now = format_utc(now_utc())
        with self.con:
            self.con.execute(
                "UPDATE feed_polls SET status='not_modified',ended_at=?,http_status=304 WHERE poll_id=?",
                (now, poll),
            )
            self.con.execute(
                "INSERT INTO feed_state(feed_id,source,url,last_checked_at,last_successful_poll_at,consecutive_failures) VALUES(?,?,?,?,?,0) ON CONFLICT(feed_id) DO UPDATE SET last_checked_at=excluded.last_checked_at,last_successful_poll_at=excluded.last_successful_poll_at,consecutive_failures=0",
                (feed, source, url, now, now),
            )

    def ingest(self, poll, feed, source, url, result, parsed, priorities, surface="section_rss"):
        from .merge import merge_sightings

        now = format_utc(now_utc())
        body = result.body
        digest = "sha256:" + __import__("hashlib").sha256(body).hexdigest()
        with self.con:
            self.con.execute(
                "INSERT OR IGNORE INTO raw_payloads VALUES(?,?,?,?,?,?)",
                (digest, "gzip", gzip.compress(body), len(body), poll, now),
            )
            seen_in_snapshot: set[str] = set()
            for candidate in parsed.entries:
                article = candidate.article.model_copy(update={"content_hash": ""})
                if article.source_id in seen_in_snapshot:
                    # A publisher listed the same article twice in one snapshot (BBC and WSJ
                    # do). The first placement is the sighting; later repeats are recorded as
                    # quarantined duplicates so the evidence stays visible without violating
                    # the one-sighting-per-poll invariant.
                    self.con.execute(
                        "INSERT INTO quarantine(poll_id,feed_id,source,item_position,stage,error_code,error_json,raw_item_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            poll,
                            feed,
                            source,
                            candidate.position,
                            "item",
                            "duplicate_in_snapshot",
                            json.dumps({"source_id": article.source_id}),
                            json.dumps(candidate.raw_item, ensure_ascii=False),
                            now,
                        ),
                    )
                    continue
                seen_in_snapshot.add(article.source_id)
                data = article.model_dump(mode="json")
                self.con.execute(
                    "INSERT INTO sightings(poll_id,feed_id,source,source_id,item_position,publisher_order,observed_at,normalized_json,raw_metadata_json,raw_item_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        poll,
                        feed,
                        source,
                        article.source_id,
                        candidate.position,
                        candidate.publisher_order,
                        now,
                        json.dumps(data, ensure_ascii=False),
                        json.dumps(article.raw_metadata, ensure_ascii=False),
                        json.dumps(candidate.raw_item, ensure_ascii=False),
                    ),
                )
            for pos, error, raw in parsed.invalid:
                self.con.execute(
                    "INSERT INTO quarantine(poll_id,feed_id,source,item_position,stage,error_code,error_json,raw_item_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        poll,
                        feed,
                        source,
                        pos,
                        "item",
                        "invalid_item",
                        json.dumps({"message": error}),
                        json.dumps(raw),
                        now,
                    ),
                )
            keys = {(x.article.source, x.article.source_id) for x in parsed.entries}
            for sid, aid in keys:
                rows = self.con.execute(
                    "SELECT normalized_json,feed_id,item_position,publisher_order FROM sightings WHERE source=? AND source_id=?",
                    (sid, aid),
                ).fetchall()
                candidates = []
                for row in rows:
                    a = ArticleSnapshot.model_validate_json(row["normalized_json"])
                    candidates.append(
                        type(
                            "C",
                            (),
                            {
                                "article": a,
                                "feed_id": row["feed_id"],
                                "position": row["item_position"],
                                "publisher_order": row["publisher_order"],
                            },
                        )()
                    )
                merged = merge_sightings(candidates, priorities)
                payload = merged.model_dump_json()
                old = self.con.execute(
                    "SELECT content_hash FROM articles WHERE source=? AND source_id=?", (sid, aid)
                ).fetchone()
                changed = not old or old[0] != merged.content_hash
                self.con.execute(
                    "INSERT INTO articles(source,source_id,snapshot_json,published_at,last_changed_at,canonical_url,content_hash) VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,source_id) DO UPDATE SET snapshot_json=excluded.snapshot_json,published_at=excluded.published_at,canonical_url=excluded.canonical_url,content_hash=excluded.content_hash,last_changed_at=CASE WHEN articles.content_hash<>excluded.content_hash THEN excluded.last_changed_at ELSE articles.last_changed_at END",
                    (
                        sid,
                        aid,
                        payload,
                        format_utc(merged.published_at),
                        now,
                        merged.canonical_url,
                        merged.content_hash,
                    ),
                )
                if changed:
                    self.con.execute(
                        "INSERT INTO article_versions(source,source_id,content_hash,observed_at,snapshot_json) VALUES(?,?,?,?,?)",
                        (sid, aid, merged.content_hash, now, payload),
                    )
            for c in parsed.entries:
                from .prominence import derive_prominence

                prominence = derive_prominence(
                    source=source,
                    surface=surface,
                    position=c.position,
                    snapshot_item_count=parsed.parsed_item_count,
                    publisher_order=c.publisher_order,
                )
                self.con.execute(
                    "INSERT INTO appearances("
                    "poll_id,source,source_id,surface_id,surface,position,publisher_order,observed_at,"
                    "snapshot_item_count,prominence_score,prominence_tier,prominence_evidence"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        poll,
                        source,
                        c.article.source_id,
                        feed,
                        surface,
                        c.position,
                        c.publisher_order,
                        now,
                        parsed.parsed_item_count,
                        prominence.score,
                        prominence.tier,
                        prominence.evidence,
                    ),
                )
            newest = max((format_utc(x.article.published_at) for x in parsed.entries), default=None)
            self.con.execute(
                "UPDATE feed_polls SET status='success',ended_at=?,http_status=?,attempt_count=?,received_etag=?,received_last_modified=?,response_hash=?,response_bytes=?,raw_item_count=?,parsed_item_count=?,valid_item_count=?,quarantined_item_count=?,warning_json=? WHERE poll_id=?",
                (
                    now,
                    result.status,
                    result.attempts,
                    result.etag,
                    result.last_modified,
                    digest,
                    len(body),
                    parsed.raw_item_count,
                    parsed.parsed_item_count,
                    len(parsed.entries),
                    len(parsed.invalid),
                    json.dumps(parsed.warnings),
                    poll,
                ),
            )
            self.con.execute(
                "INSERT INTO feed_state(feed_id,source,url,etag,last_modified,last_response_hash,last_checked_at,last_successful_poll_at,last_item_count,newest_published_at,consecutive_failures) VALUES(?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(feed_id) DO UPDATE SET etag=excluded.etag,last_modified=excluded.last_modified,last_response_hash=excluded.last_response_hash,last_checked_at=excluded.last_checked_at,last_successful_poll_at=excluded.last_successful_poll_at,last_item_count=excluded.last_item_count,newest_published_at=excluded.newest_published_at,consecutive_failures=0",
                (
                    feed,
                    source,
                    url,
                    result.etag,
                    result.last_modified,
                    digest,
                    now,
                    now,
                    len(parsed.entries),
                    newest,
                ),
            )
