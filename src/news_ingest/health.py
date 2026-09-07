from __future__ import annotations

from .db import Database


def health(database, threshold=3):
    db = Database(database)
    try:
        integrity = db.con.execute("PRAGMA integrity_check").fetchone()[0]
        feeds = [
            dict(r) for r in db.con.execute("SELECT * FROM feed_state ORDER BY source,feed_id")
        ]
        reasons = []
        if integrity != "ok":
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
        db.close()
