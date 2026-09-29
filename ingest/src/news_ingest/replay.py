from __future__ import annotations

import sqlite3
from pathlib import Path

from .collect import process_lock
from .db import connect, migrate, rebuild_projection


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
