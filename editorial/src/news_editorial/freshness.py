"""Is the paper on the site fresh? Reads block 3's activations, never the run directories."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .memory import activated_editions


def latest_activated(publish_root: Path) -> dict[str, Any] | None:
    records = activated_editions(publish_root)
    if not records:
        return None
    top = records[0]
    return {
        "edition_id": top["activation"]["edition_id"],
        "sequence": top["activation"]["sequence"],
        "activated_at": top["activation"]["activated_at"],
        "cutoff_at": top["edition"]["edition"]["cutoff_at"],
        "date": top["edition"]["edition"]["date"],
    }


def staleness(publish_root: Path, now: str | None = None, max_age_hours: float = 30.0) -> dict[str, Any]:
    moment = dt.datetime.fromisoformat(now.replace("Z", "+00:00")) if now else dt.datetime.now(dt.UTC)
    latest = latest_activated(publish_root)
    if latest is None:
        return {"edition_id": None, "cutoff_at": None, "age_hours": None, "max_age_hours": max_age_hours, "stale": True}
    cutoff = dt.datetime.fromisoformat(latest["cutoff_at"].replace("Z", "+00:00"))
    age = round((moment - cutoff).total_seconds() / 3600, 2)
    return {**latest, "age_hours": age, "max_age_hours": max_age_hours, "stale": age > max_age_hours}
