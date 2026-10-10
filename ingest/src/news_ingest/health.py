from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .db import connect, used_bytes
from .time import format_utc, now_utc

GROWTH_WINDOW = timedelta(days=7)


def storage(con, database, growth_alert_mb_per_day):
    """Sizes, free disk, and growth per day from the used bytes each collection records."""
    path = Path(database)
    wal = path.with_name(path.name + "-wal")
    file_bytes = path.stat().st_size
    used = used_bytes(con)
    samples = con.execute(
        "SELECT started_at,json_extract(summary_json,'$.database_used_bytes') FROM fetch_runs "
        "WHERE started_at>=? AND json_extract(summary_json,'$.database_used_bytes') IS NOT NULL "
        "ORDER BY started_at",
        (format_utc(now_utc() - GROWTH_WINDOW),),
    ).fetchall()
    growth = days = None
    if samples:
        first, last = (datetime.fromisoformat(samples[i][0]) for i in (0, -1))
        span = (last - first).total_seconds() / 86400
        # Daily compaction makes a shorter span misleading; wait for one whole day.
        if span >= 1:
            growth, days = round((samples[-1][1] - samples[0][1]) / span), round(span, 2)
    disk_free = shutil.disk_usage(path.parent).free
    alerts = []
    if growth is not None and growth > growth_alert_mb_per_day * 1048576:
        alerts.append(f"database_growth:{growth // 1048576}MB_per_day")
    # A backup or VACUUM needs room for another full copy, with margin.
    if disk_free < 2 * file_bytes:
        alerts.append("disk_headroom")
    return {
        "file_bytes": file_bytes,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        "used_bytes": used,
        "free_page_bytes": con.execute("PRAGMA freelist_count").fetchone()[0]
        * con.execute("PRAGMA page_size").fetchone()[0],
        "disk_free_bytes": disk_free,
        "growth_bytes_per_day": growth,
        "growth_window_days": days,
        "growth_alert_bytes_per_day": growth_alert_mb_per_day * 1048576,
    }, alerts


def health(database, threshold=3, deep=False, growth_alert_mb_per_day=250):
    """Per-feed collection health and database storage, in milliseconds. The integrity check reads
    every page of the database and is only run on request (`--deep`): it took over two minutes at
    6 GB and failed the desk's morning run on 9 October 2026."""
    con = connect(database, readonly=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0] if deep else "not_checked"
        feeds = [dict(r) for r in con.execute("SELECT * FROM feed_state ORDER BY source,feed_id")]
        database_report, storage_alerts = storage(con, database, growth_alert_mb_per_day)
        reasons = []
        if deep and integrity != "ok":
            reasons.append("integrity_check_failed")
        reasons += [
            f"feed_failures:{x['feed_id']}" for x in feeds if x["consecutive_failures"] >= threshold
        ]
        reasons += storage_alerts
        return {
            "status": "healthy" if not reasons else "degraded",
            "integrity": integrity,
            "feeds": feeds,
            "database": database_report,
            "reasons": reasons,
        }
    finally:
        con.close()
