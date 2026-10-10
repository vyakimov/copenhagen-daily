from __future__ import annotations

import sqlite3
from pathlib import Path

from .collect import process_lock
from .db import connect, has_sighting_content, migrate, rebuild_projection


def backup(database, output):
    output = Path(output)
    if output.exists():
        raise ValueError("backup already exists")
    src = connect(database, True)
    dst = sqlite3.connect(output)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def restore_check(backup_path):
    src = connect(backup_path, readonly=True)
    result = src.execute("PRAGMA integrity_check").fetchone()[0]
    src.close()
    return {"integrity": result, "ok": result == "ok"}


def deduplicate_sightings(database, backup_path, lock_path):
    with process_lock(lock_path):
        con = connect(database)
        try:
            if has_sighting_content(con):
                return {"already_deduplicated": True, "migrated": False}
            backup(database, backup_path)
            if not restore_check(backup_path)["ok"]:
                raise ValueError("backup integrity check failed; migration was not started")
            verification = migrate(con, allow_content_migration=True)
            return {
                **verification,
                "already_deduplicated": False,
                "migrated": True,
                "backup": str(backup_path),
                "vacuum_performed": False,
            }
        finally:
            con.close()


def rebuild_articles(database, source=None, dry_run=False, *, priorities, lock_path):
    from contextlib import nullcontext

    # Dry-run uses a read-only database snapshot and writes only connection-local TEMP tables.
    with nullcontext() if dry_run else process_lock(lock_path):
        con = connect(database, readonly=dry_run)
        try:
            if not dry_run:
                migrate(con)
            return rebuild_projection(con, priorities, source, dry_run)
        finally:
            con.close()


def compact_history(database, *, keep_days, lock_path, dry_run=False, vacuum=False, now=None):
    """Archive raw payloads and fold repeated sightings and appearances older than `keep_days`.

    Each step commits per feed (or feed-day), so an interruption leaves finished feeds compacted
    and the rest untouched. Free pages are reused by later writes; `vacuum` also returns them to
    the filesystem, which needs free disk for a full copy of the compacted database."""
    from contextlib import nullcontext
    from datetime import timedelta

    from .db import (
        apply_run_plan,
        archive_payload_day,
        has_column,
        plan_payload_archives,
        stage_poll_ordinals,
        stage_run_plan,
    )
    from .time import format_utc, now_utc

    cutoff = (now or now_utc()) - timedelta(days=keep_days)
    cutoff_at, before_day = format_utc(cutoff), cutoff.date().isoformat()
    with nullcontext() if dry_run else process_lock(lock_path):
        con = connect(database, readonly=dry_run)
        try:
            if not dry_run:
                migrate(con)
            if not has_sighting_content(con):
                raise ValueError("compaction requires the migration 005 sighting layout")
            if dry_run:
                # One read snapshot for every count below.
                con.execute("BEGIN")
            days = plan_payload_archives(con, before_day)
            stage_poll_ordinals(con)
            runs = {
                table: stage_run_plan(con, table, cutoff_at)
                for table in ("sightings", "appearances")
            }
            result = {
                "dry_run": dry_run,
                "keep_days": keep_days,
                "cutoff": cutoff_at,
                "payloads": {
                    "archives": len(days),
                    "bodies": sum(day["bodies"] for day in days),
                    "gzip_bytes": sum(day["gzip_bytes"] for day in days),
                    "archive_bytes": None,
                },
                **{
                    table: {"runs": started, "rows_removed": removed}
                    for table, (started, removed) in runs.items()
                },
                "vacuum_performed": False,
            }
            if dry_run:
                con.rollback()
                return result
            if not has_column(con, "sightings", "run_polls"):
                raise ValueError("migration 006 is not installed")
            result["payloads"]["archive_bytes"] = sum(
                archive_payload_day(con, day["feed_id"], day["day"]) for day in days
            )
            for table in runs:
                apply_run_plan(con, table)
            page_size = con.execute("PRAGMA page_size").fetchone()[0]
            result["database_free_bytes"] = (
                con.execute("PRAGMA freelist_count").fetchone()[0] * page_size
            )
            if vacuum:
                # Planning left an implicit transaction open on its temporary tables.
                con.commit()
                con.execute("VACUUM")
                result["vacuum_performed"] = True
            result["database_bytes"] = con.execute("PRAGMA page_count").fetchone()[0] * page_size
            return result
        finally:
            con.close()


def collapse_versions(database, *, lock_path, source=None, dry_run=False):
    """Remove article versions that repeat their predecessor under the current content rule."""
    from contextlib import nullcontext

    from .db import remove_staged_versions, stage_version_collapse

    with nullcontext() if dry_run else process_lock(lock_path):
        con = connect(database, readonly=dry_run)
        try:
            if dry_run:
                con.execute("BEGIN")
            result = {"dry_run": dry_run, **stage_version_collapse(con, source)}
            if dry_run:
                con.rollback()
                return result
            remove_staged_versions(con)
            return result
        finally:
            con.close()
