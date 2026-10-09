from __future__ import annotations

from .db import connect


def health(database, threshold=3, deep=False):
    """Per-feed collection health in milliseconds. The integrity check reads every page of the
    database and is only run on request (`--deep`): it took over two minutes at 6 GB and failed the
    desk's morning run on 9 October 2026."""
    con = connect(database, readonly=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0] if deep else "not_checked"
        feeds = [dict(r) for r in con.execute("SELECT * FROM feed_state ORDER BY source,feed_id")]
        reasons = []
        if deep and integrity != "ok":
            reasons.append("integrity_check_failed")
        reasons += [
            f"feed_failures:{x['feed_id']}" for x in feeds if x["consecutive_failures"] >= threshold
        ]
        return {
            "status": "healthy" if not reasons else "degraded",
            "integrity": integrity,
            "feeds": feeds,
            "reasons": reasons,
        }
    finally:
        con.close()
