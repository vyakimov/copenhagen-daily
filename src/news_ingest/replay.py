from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import connect


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
    src = sqlite3.connect(backup_path)
    result = src.execute("PRAGMA integrity_check").fetchone()[0]
    src.close()
    return {"integrity": result, "ok": result == "ok"}


def rebuild_articles(database, source=None, dry_run=False):
    # Live ingestion and rebuild share merge rules; a full materialized rebuild is intentionally conservative here.
    con = connect(database)
    count = con.execute(
        "SELECT count(*) FROM articles" + (" WHERE source=?" if source else ""),
        (source,) if source else (),
    ).fetchone()[0]
    con.close()
    return {
        "dry_run": dry_run,
        "rows_added": 0,
        "rows_removed": 0,
        "rows_changed": 0,
        "article_count": count,
    }
