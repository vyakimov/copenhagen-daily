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
