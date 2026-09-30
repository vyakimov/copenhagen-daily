from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from .models import ArticleSnapshot, FeedMergeState
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


def migrate(con: sqlite3.Connection, *, allow_content_migration=False) -> dict:
    verification = {}
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    folder = Path(__file__).parents[2] / "migrations"
    for file in sorted(folder.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(file.name[:3])
        if not con.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
        ).fetchone():
            if (
                version == 5
                and not allow_content_migration
                and con.execute("SELECT 1 FROM sightings LIMIT 1").fetchone()
            ):
                break
            try:
                # executescript otherwise commits before executing; put BEGIN inside the script.
                con.executescript("BEGIN IMMEDIATE;\n" + file.read_text())
                if version == 5:
                    verification = migrate_sighting_content(con)
                con.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)", (version, format_utc(now_utc()))
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
    return verification


def has_sighting_content(con):
    return any(row[1] == "content_id" for row in con.execute("PRAGMA table_info(sightings)"))


def store_sighting_content(con, source, source_id, normalized, raw_metadata, raw_item):
    from .sighting_content import restore_observation, split_observation, storage_digest

    template, observation = split_observation(normalized)
    if restore_observation(template, observation) != normalized:
        raise ValueError("sighting content did not round-trip exactly")
    digest = storage_digest(source, source_id, template, raw_metadata, raw_item)
    values = (template, raw_metadata, raw_item)
    con.execute(
        "INSERT INTO sighting_contents(storage_hash,normalized_template,raw_metadata_json,raw_item_json) "
        "VALUES(?,?,?,?) ON CONFLICT(storage_hash) DO NOTHING",
        (digest, *values),
    )
    stored = con.execute(
        "SELECT content_id,normalized_template,raw_metadata_json,raw_item_json "
        "FROM sighting_contents WHERE storage_hash=?",
        (digest,),
    ).fetchone()
    if tuple(stored)[1:] != values:
        raise ValueError("sighting storage digest collision or corrupt content")
    return stored[0], observation


def migrate_sighting_content(con):
    previous_sequence = con.execute(
        "SELECT seq FROM sqlite_sequence WHERE name='sightings'"
    ).fetchone()
    count = 0
    original_hash = hashlib.sha256()
    for row in con.execute("SELECT * FROM sightings ORDER BY source,source_id,sighting_id"):
        original_hash.update(json.dumps(dict(row), sort_keys=True, ensure_ascii=False).encode())
        original_hash.update(b"\n")
        content_id, observation = store_sighting_content(
            con,
            row["source"],
            row["source_id"],
            row["normalized_json"],
            row["raw_metadata_json"],
            row["raw_item_json"],
        )
        con.execute(
            "INSERT INTO sightings_v5 VALUES(?,?,?,?,?,?,?,?,?,?)",
            (*tuple(row)[:8], content_id, observation),
        )
        count += 1
    if con.execute("SELECT count(*) FROM sightings_v5").fetchone()[0] != count:
        raise ValueError("sighting migration count mismatch")
    # No tables reference sightings; stable IDs preserve merge watermarks and all observations.
    con.execute("DROP TABLE sightings")
    con.execute("ALTER TABLE sightings_v5 RENAME TO sightings")
    con.execute("CREATE INDEX sightings_article_idx ON sightings(source,source_id)")
    if previous_sequence is not None:
        updated = con.execute(
            "UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name='sightings'",
            (previous_sequence[0],),
        )
        if not updated.rowcount:
            con.execute(
                "INSERT INTO sqlite_sequence VALUES('sightings',?)", (previous_sequence[0],)
            )
    if con.execute("PRAGMA foreign_key_check(sightings)").fetchone():
        raise ValueError("sighting migration foreign-key mismatch")
    restored_hash = hashlib.sha256()
    for row in read_sightings(con, include_raw=True):
        restored_hash.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
        restored_hash.update(b"\n")
    if restored_hash.digest() != original_hash.digest():
        raise ValueError("sighting migration reconstruction mismatch")
    return {
        "sightings_verified": count,
        "sightings_sha256": original_hash.hexdigest(),
        "distinct_contents": con.execute("SELECT count(*) FROM sighting_contents").fetchone()[0],
    }


def read_sightings(con, source=None, source_id=None, after_id=0, poll_id=None, include_raw=False):
    from .sighting_content import restore_observation

    clauses = ["s.sighting_id>?"]
    params = [after_id]
    for field, value in (("source", source), ("source_id", source_id), ("poll_id", poll_id)):
        if value is not None:
            clauses.append(f"s.{field}=?")
            params.append(value)
    compact = has_sighting_content(con)
    if compact:
        columns = "s.*,c.normalized_template"
        if include_raw:
            columns += ",c.raw_metadata_json,c.raw_item_json"
        query = f"SELECT {columns} FROM sightings s LEFT JOIN sighting_contents c USING(content_id)"
    else:
        columns = (
            "s.sighting_id,s.poll_id,s.feed_id,s.source,s.source_id,s.item_position,"
            "s.publisher_order,s.observed_at,s.normalized_json"
        )
        if include_raw:
            columns += ",s.raw_metadata_json,s.raw_item_json"
        query = f"SELECT {columns} FROM sightings s"
    query += " WHERE " + " AND ".join(clauses) + " ORDER BY s.source,s.source_id,s.sighting_id"
    for row in con.execute(query, params):
        value = dict(row)
        if compact:
            try:
                value["normalized_json"] = restore_observation(
                    value.pop("normalized_template"), value.pop("observation_json")
                )
            except (TypeError, ValueError) as exc:
                raise RebuildError(
                    "rebuild_invalid_sighting",
                    "Stored sighting content cannot be reconstructed.",
                    {"sighting_id": value["sighting_id"]},
                ) from exc
            value.pop("content_id")
        yield value


class RebuildError(ValueError):
    def __init__(self, code, message, details):
        super().__init__(message)
        self.code = code
        self.details = details


def deduplication_report(database):
    from .sighting_content import split_observation, storage_digest

    con = connect(database, readonly=True)
    seen = set()
    rows = repeated_bytes = unique_bytes = observation_bytes = 0
    try:
        con.execute("BEGIN")
        for row in read_sightings(con, include_raw=True):
            template, observation = split_observation(row["normalized_json"])
            digest = storage_digest(
                row["source"],
                row["source_id"],
                template,
                row["raw_metadata_json"],
                row["raw_item_json"],
            )
            repeated_bytes += sum(
                len(row[key].encode())
                for key in ("normalized_json", "raw_metadata_json", "raw_item_json")
            )
            observation_bytes += len(observation.encode())
            if digest not in seen:
                seen.add(digest)
                unique_bytes += sum(
                    len(value.encode())
                    for value in (template, row["raw_metadata_json"], row["raw_item_json"])
                )
            rows += 1
        return {
            "dry_run": True,
            "already_deduplicated": has_sighting_content(con),
            "sightings": rows,
            "distinct_contents": len(seen),
            "repeated_json_bytes": repeated_bytes,
            "unique_content_json_bytes": unique_bytes,
            "observation_json_bytes": observation_bytes,
            "estimated_json_bytes_saved": repeated_bytes - unique_bytes - observation_bytes,
            "database_allocated_bytes": (
                con.execute("PRAGMA page_count").fetchone()[0]
                * con.execute("PRAGMA page_size").fetchone()[0]
            ),
            "database_free_bytes": (
                con.execute("PRAGMA freelist_count").fetchone()[0]
                * con.execute("PRAGMA page_size").fetchone()[0]
            ),
            "excludes": "SQLite pages, indexes, keys, and unchanged observation columns",
        }
    finally:
        con.close()


def rebuild_projection(con, priorities, source=None, dry_run=False):
    """Stage a complete projection in a consistent snapshot, then atomically reconcile it."""
    from datetime import datetime
    from itertools import groupby

    from .feed import SightingCandidate
    from .merge import MergeAccumulator, merge_feed_states, update_feed_state

    counts = {}

    def source_counts(sid):
        return counts.setdefault(
            sid,
            {
                "rows_added": 0,
                "rows_removed": 0,
                "rows_changed": 0,
                "article_count": 0,
                "blocked_removals": 0,
            },
        )

    if source is not None:
        source_counts(source)
    con.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
    try:
        con.execute(
            "CREATE TEMP TABLE rebuilt_articles ("
            "source TEXT NOT NULL, source_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,"
            "published_at TEXT NOT NULL, last_changed_at TEXT NOT NULL, canonical_url TEXT,"
            "content_hash TEXT NOT NULL, needs_write INTEGER NOT NULL, PRIMARY KEY(source,source_id))"
        )
        con.execute(
            "CREATE TEMP TABLE rebuilt_feed_states (source TEXT,source_id TEXT,feed_id TEXT,"
            "state_json TEXT,PRIMARY KEY(source,source_id,feed_id))"
        )
        con.execute(
            "CREATE TEMP TABLE rebuilt_merge_heads (source TEXT,source_id TEXT,last_sighting_id INTEGER,"
            "state_count INTEGER,PRIMARY KEY(source,source_id))"
        )
        rows = read_sightings(con, source=source)
        sightings_read = 0
        states_rebuilt = 0
        for (sid, aid), history in groupby(rows, key=lambda row: (row["source"], row["source_id"])):
            state = MergeAccumulator(priorities)
            feed_states = {}
            last_hash = last_changed_at = None
            for row in history:
                if row["feed_id"] not in priorities:
                    raise RebuildError(
                        "rebuild_unknown_feed",
                        "Retained sighting references a feed missing from configuration.",
                        {"feed_id": row["feed_id"], "sighting_id": row["sighting_id"]},
                    )
                try:
                    article = ArticleSnapshot.model_validate_json(row["normalized_json"])
                    if (article.source, article.source_id) != (sid, aid) or row[
                        "item_position"
                    ] < 1:
                        raise ValueError("sighting identity or position mismatch")
                    # Enforce usable timezone-aware timestamps, including historical commit time.
                    for value in (
                        article.published_at,
                        article.first_seen_at,
                        article.last_seen_at,
                        article.last_checked_at,
                        article.modified_at,
                    ):
                        if value is not None:
                            format_utc(value)
                    observed_at = format_utc(datetime.fromisoformat(row["observed_at"]))
                    state.add(
                        SightingCandidate(
                            article,
                            row["feed_id"],
                            row["item_position"],
                            row["publisher_order"],
                            {},
                        )
                    )
                    merged = ArticleSnapshot.model_validate(state.snapshot().model_dump())
                    feed_states[row["feed_id"]] = update_feed_state(
                        feed_states.get(row["feed_id"]), row["feed_id"], row["sighting_id"], article
                    )
                except (ValueError, TypeError) as exc:
                    raise RebuildError(
                        "rebuild_invalid_sighting",
                        "A retained sighting cannot produce a valid article; projection unchanged.",
                        {"sighting_id": row["sighting_id"]},
                    ) from exc
                if merged.content_hash != last_hash:
                    last_changed_at = observed_at
                    last_hash = merged.content_hash
                sightings_read += 1
            if merge_feed_states(list(feed_states.values()), priorities) != merged:
                raise RebuildError(
                    "rebuild_merge_state_mismatch",
                    "Merge state differs from full history; projection unchanged.",
                    {"source": sid, "source_id": aid},
                )
            for feed_id, feed_state in sorted(feed_states.items()):
                con.execute(
                    "INSERT INTO rebuilt_feed_states VALUES(?,?,?,?)",
                    (sid, aid, feed_id, feed_state.model_dump_json()),
                )
                states_rebuilt += 1
            con.execute(
                "INSERT INTO rebuilt_merge_heads VALUES(?,?,?,?)",
                (sid, aid, row["sighting_id"], len(feed_states)),
            )
            snapshot = merged.model_dump_json()
            published_at = format_utc(merged.published_at)
            old = con.execute(
                "SELECT * FROM articles WHERE source=? AND source_id=?", (sid, aid)
            ).fetchone()
            changed = old is not None and (
                json.dumps(json.loads(old["snapshot_json"]), sort_keys=True)
                != json.dumps(json.loads(snapshot), sort_keys=True)
                or old["published_at"] != published_at
                or old["last_changed_at"] != last_changed_at
                or old["canonical_url"] != merged.canonical_url
                or old["content_hash"] != merged.content_hash
            )
            count = source_counts(sid)
            count["article_count"] += 1
            count["rows_added"] += int(old is None)
            count["rows_changed"] += int(changed)
            con.execute(
                "INSERT INTO rebuilt_articles VALUES(?,?,?,?,?,?,?,?)",
                (
                    sid,
                    aid,
                    snapshot,
                    published_at,
                    last_changed_at,
                    merged.canonical_url,
                    merged.content_hash,
                    int(old is None or changed),
                ),
            )
        con.execute(
            "CREATE TEMP TABLE rebuild_removed (source TEXT,source_id TEXT,PRIMARY KEY(source,source_id))"
        )
        con.execute(
            "INSERT INTO rebuild_removed SELECT a.source,a.source_id FROM articles a "
            "LEFT JOIN rebuilt_articles r USING(source,source_id) "
            "WHERE r.source IS NULL" + (" AND a.source=?" if source is not None else ""),
            (source,) if source is not None else (),
        )
        for row in con.execute("SELECT source,count(*) FROM rebuild_removed GROUP BY source"):
            source_counts(row[0])["rows_removed"] = row[1]
        for row in con.execute(
            "SELECT source,count(*) FROM (SELECT DISTINCT v.source,v.source_id "
            "FROM article_versions v JOIN rebuild_removed r USING(source,source_id)) GROUP BY source"
        ):
            source_counts(row[0])["blocked_removals"] = row[1]
        result = {
            "dry_run": dry_run,
            **{
                key: sum(count[key] for count in counts.values())
                for key in (
                    "rows_added",
                    "rows_removed",
                    "rows_changed",
                    "article_count",
                    "blocked_removals",
                )
            },
            "sightings_read": sightings_read,
            "merge_states_rebuilt": states_rebuilt,
            "by_source": {sid: counts[sid] for sid in sorted(counts)},
        }
        if dry_run:
            con.rollback()
            return result
        if result["blocked_removals"]:
            raise RebuildError(
                "rebuild_conflict",
                "Articles without sightings still have historical versions; refusing to remove them.",
                result,
            )
        con.execute(
            "INSERT INTO articles(source,source_id,snapshot_json,published_at,last_changed_at,"
            "canonical_url,content_hash) SELECT source,source_id,snapshot_json,published_at,"
            "last_changed_at,canonical_url,content_hash FROM rebuilt_articles WHERE needs_write=1 "
            "ON CONFLICT(source,source_id) DO UPDATE SET snapshot_json=excluded.snapshot_json,"
            "published_at=excluded.published_at,last_changed_at=excluded.last_changed_at,"
            "canonical_url=excluded.canonical_url,content_hash=excluded.content_hash"
        )
        con.execute(
            "DELETE FROM articles WHERE (source,source_id) IN "
            "(SELECT source,source_id FROM rebuild_removed)"
        )
        for table in ("article_feed_merge_state", "article_merge_heads"):
            con.execute(
                f"DELETE FROM {table}" + (" WHERE source=?" if source is not None else ""),
                (source,) if source is not None else (),
            )
        con.execute("INSERT INTO article_feed_merge_state SELECT * FROM rebuilt_feed_states")
        con.execute("INSERT INTO article_merge_heads SELECT * FROM rebuilt_merge_heads")
        con.execute("DROP TABLE rebuilt_feed_states")
        con.execute("DROP TABLE rebuilt_merge_heads")
        con.execute("DROP TABLE rebuilt_articles")
        con.execute("DROP TABLE rebuild_removed")
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise


class Database:
    def __init__(self, path):
        self.path = path
        self.con = connect(path)
        migrate(self.con)
        self.compact_sightings = has_sighting_content(self.con)

    def close(self):
        self.con.close()

    def insert_sighting(self, values):
        # Caller owns the feed transaction. Content and its observation must commit together.
        if self.compact_sightings:
            content_id, observation = store_sighting_content(
                self.con, values[2], values[3], *values[7:]
            )
            self.con.execute(
                "INSERT INTO sightings(poll_id,feed_id,source,source_id,item_position,publisher_order,"
                "observed_at,content_id,observation_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (*values[:7], content_id, observation),
            )
        else:
            self.con.execute(
                "INSERT INTO sightings(poll_id,feed_id,source,source_id,item_position,publisher_order,"
                "observed_at,normalized_json,raw_metadata_json,raw_item_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                values,
            )

    def merge_article(self, source, source_id, priorities):
        """Advance disposable per-feed state using only sightings beyond its durable watermark."""
        from .merge import merge_feed_states, update_feed_state

        head = self.con.execute(
            "SELECT last_sighting_id,state_count FROM article_merge_heads WHERE source=? AND source_id=?",
            (source, source_id),
        ).fetchone()
        cached = self.con.execute(
            "SELECT feed_id,state_json FROM article_feed_merge_state "
            "WHERE source=? AND source_id=? ORDER BY feed_id",
            (source, source_id),
        ).fetchall()
        states = {}
        through = 0
        if head is not None and len(cached) == head["state_count"]:
            try:
                for row in cached:
                    state = FeedMergeState.model_validate_json(row["state_json"])
                    if (state.source, state.source_id, state.feed_id) != (
                        source,
                        source_id,
                        row["feed_id"],
                    ):
                        raise ValueError("merge state identity mismatch")
                    for representative in state.representatives:
                        if representative.sighting_id > head["last_sighting_id"] or (
                            representative.article.source,
                            representative.article.source_id,
                        ) != (source, source_id):
                            raise ValueError("merge representative identity or watermark mismatch")
                    states[row["feed_id"]] = state
                through = head["last_sighting_id"]
            except ValueError:
                states = {}
        bootstrapped = through == 0
        if bootstrapped:
            self.con.execute(
                "DELETE FROM article_feed_merge_state WHERE source=? AND source_id=?",
                (source, source_id),
            )
        rows_read = 0
        changed_feeds = set()
        for row in read_sightings(self.con, source=source, source_id=source_id, after_id=through):
            article = ArticleSnapshot.model_validate_json(row["normalized_json"])
            if (article.source, article.source_id) != (source, source_id):
                raise ValueError("sighting identity mismatch")
            feed_id = row["feed_id"]
            states[feed_id] = update_feed_state(
                states.get(feed_id), feed_id, row["sighting_id"], article
            )
            through = row["sighting_id"]
            changed_feeds.add(feed_id)
            rows_read += 1
        merged = merge_feed_states(list(states.values()), priorities)
        for feed_id in sorted(changed_feeds):
            self.con.execute(
                "INSERT INTO article_feed_merge_state VALUES(?,?,?,?) "
                "ON CONFLICT(source,source_id,feed_id) DO UPDATE SET state_json=excluded.state_json",
                (source, source_id, feed_id, states[feed_id].model_dump_json()),
            )
        self.con.execute(
            "INSERT INTO article_merge_heads VALUES(?,?,?,?) ON CONFLICT(source,source_id) "
            "DO UPDATE SET last_sighting_id=excluded.last_sighting_id,state_count=excluded.state_count",
            (source, source_id, through, len(states)),
        )
        return merged, {
            "historical_rows_read": rows_read,
            "merge_state_rows_read": len(cached),
            "merge_state_bootstraps": int(bootstrapped),
        }

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
        metrics = {
            "sightings_inserted": 0,
            "historical_rows_read": 0,
            "merge_state_rows_read": 0,
            "merge_state_bootstraps": 0,
        }
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
                self.insert_sighting(
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
                metrics["sightings_inserted"] += 1
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
            for sid, aid in sorted(keys):
                merged, merge_metrics = self.merge_article(sid, aid, priorities)
                for key, value in merge_metrics.items():
                    metrics[key] += value
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
        return metrics
