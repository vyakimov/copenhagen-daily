from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .db import connect
from .models import AppearanceRecord, ArticleSnapshot, PublisherProminence
from .time import format_utc, now_utc


def _boundary(value: str) -> str:
    """Validate an explicit UTC RFC3339 CLI boundary."""
    from datetime import datetime

    if not value.endswith("Z"):
        raise ValueError("export boundary must be UTC RFC3339 with Z")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid export boundary") from exc
    return format_utc(parsed)


def plan_export(output, since=None, until=None, changed_since=None):
    if bool(since) == bool(changed_since):
        raise ValueError("choose exactly one export mode")
    if since:
        if not until:
            raise ValueError("--until is required with --since")
        start = _boundary(since)
        end = _boundary(until)
        if start >= end:
            raise ValueError("since must precede until")
        mode = "publication_window"
    else:
        if until:
            raise ValueError("--until is valid only with --since")
        start = end = None
        changed_since = _boundary(changed_since)
        mode = "changed_since"
    output = Path(output)
    if output.exists():
        raise ValueError("output already exists")
    return {
        "mode": mode,
        "window": {"since": start, "until": end} if since else None,
        "changed_since": changed_since if not since else None,
        "output": str(output),
        "format": "jsonl",
    }


def export_bundle(
    database,
    output,
    since=None,
    until=None,
    changed_since=None,
    lock_path=None,
    lock_wait_seconds=90,
):
    """Write a bundle. With a lock path the export holds the collector's process lock while it reads
    and stamps `generated_at`, waiting up to `lock_wait_seconds` for a poll in flight to finish; a
    poll commits rows stamped with a time taken before its transaction, so an export that read
    beside it could stamp a cursor those rows fall behind."""
    if lock_path is None:
        return _export_bundle(database, output, since, until, changed_since)
    from .collect import process_lock

    deadline = time.monotonic() + lock_wait_seconds
    while True:
        try:
            with process_lock(lock_path):
                return _export_bundle(database, output, since, until, changed_since)
        except RuntimeError as exc:
            if str(exc) != "lock_busy" or time.monotonic() >= deadline:
                raise
            time.sleep(1)


def _export_bundle(database, output, since=None, until=None, changed_since=None):
    plan = plan_export(output, since, until, changed_since)
    if plan["mode"] == "publication_window":
        start = plan["window"]["since"]
        end = plan["window"]["until"]
        where = "published_at>=? AND published_at<?"
        values = (start, end)
    else:
        start = end = None
        where = "last_changed_at>=?"
        values = (plan["changed_since"],)
    mode = plan["mode"]
    output = Path(output)
    con = connect(database, True)
    con.execute("BEGIN")
    generated = format_utc(now_utc())
    rows = con.execute(
        f"SELECT * FROM articles WHERE {where} ORDER BY published_at,source,source_id", values
    ).fetchall()
    keys = {(r["source"], r["source_id"]) for r in rows}
    app = [
        r
        for r in con.execute(
            "SELECT * FROM appearances ORDER BY observed_at,source,source_id,surface_id,position"
        )
        if (r["source"], r["source_id"]) in keys
    ]
    con.close()
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=output.parent))
    files = {}
    try:
        article_path = stage / "articles.jsonl"
        best_prominence = {}
        for appearance_row in app:
            key = (appearance_row["source"], appearance_row["source_id"])
            candidate_rank = (
                appearance_row["prominence_score"],
                appearance_row["observed_at"],
                -appearance_row["position"],
            )
            current = best_prominence.get(key)
            if current is None or candidate_rank > current[0]:
                best_prominence[key] = (candidate_rank, appearance_row)
        with article_path.open("w", encoding="utf8", newline="\n") as f:
            for row in rows:
                article = ArticleSnapshot.model_validate_json(row["snapshot_json"])
                selected = best_prominence.get((row["source"], row["source_id"]))
                if selected:
                    appearance_row = selected[1]
                    article.publisher_prominence = PublisherProminence(
                        score=appearance_row["prominence_score"],
                        tier=appearance_row["prominence_tier"],
                        evidence=appearance_row["prominence_evidence"],
                        surface_id=appearance_row["surface_id"],
                        surface=appearance_row["surface"],
                        position=appearance_row["position"],
                        snapshot_item_count=appearance_row["snapshot_item_count"],
                        observed_at=appearance_row["observed_at"],
                    )
                f.write(article.model_dump_json() + "\n")
        if app:
            with (stage / "appearances.jsonl").open("w", encoding="utf8", newline="\n") as f:
                for r in app:
                    appearance = AppearanceRecord.model_validate(
                        {
                            "poll_id": r["poll_id"],
                            "source": r["source"],
                            "source_id": r["source_id"],
                            "surface_id": r["surface_id"],
                            "surface": r["surface"],
                            "surface_section": r["surface_section"],
                            "position": r["position"],
                            "publisher_order": r["publisher_order"],
                            "is_super_article": (
                                bool(r["is_super_article"])
                                if r["is_super_article"] is not None
                                else None
                            ),
                            "observed_at": r["observed_at"],
                            "snapshot_item_count": r["snapshot_item_count"],
                            "prominence_score": r["prominence_score"],
                            "prominence_tier": r["prominence_tier"],
                            "prominence_evidence": r["prominence_evidence"],
                        }
                    )
                    f.write(appearance.model_dump_json() + "\n")
        for path in stage.glob("*.jsonl"):
            b = path.read_bytes()
            files[path.name] = {
                "sha256": "sha256:" + hashlib.sha256(b).hexdigest(),
                "bytes": len(b),
            }
        manifest = {
            "schema_version": 1,
            "generated_at": generated,
            "export_mode": mode,
            "window": {"since": start, "until": end} if since else None,
            "changed_since": None if since else values[0],
            "article_count": len(rows),
            "appearance_count": len(app),
            "files": files,
            "coverage_gaps": [],
            "warnings": [],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf8"
        )
        os.rename(stage, output)
        return manifest
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
