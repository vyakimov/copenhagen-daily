"""Safe RSS fixture capture used by the whitelisted CLI entrypoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from .config import AppConfig
from .http import fetch
from .time import format_utc, now_utc


async def capture_fixture(
    config: AppConfig,
    feed_id: str,
    output: str | Path,
    *,
    dry_run: bool = False,
) -> dict:
    matches = [(source, feed) for source, _, feed in config.enabled_feeds() if feed.id == feed_id]
    valid = sorted(feed.id for _, _, feed in config.enabled_feeds())
    if not matches:
        raise ValueError(f"unknown --feed-id '{feed_id}'; valid values: {', '.join(valid)}")

    source, feed = matches[0]
    target = Path(output)
    sidecar = target.with_suffix(target.suffix + ".json")
    for path in (target, sidecar):
        if path.exists():
            raise ValueError(f"fixture target already exists: {path}")
    if not target.parent.exists():
        raise FileNotFoundError(target.parent)

    plan = {
        "dry_run": dry_run,
        "feed_id": feed.id,
        "source": source,
        "url": str(feed.url),
        "output": str(target),
        "sidecar": str(sidecar),
    }
    if dry_run:
        return plan

    timeout = httpx.Timeout(config.http.timeout_seconds)
    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=timeout) as client:
        result = await fetch(
            client,
            str(feed.url),
            None,
            config.http,
            config.max_response_bytes,
        )
    metadata = {
        "feed_id": feed.id,
        "source": source,
        "url": str(feed.url),
        "final_url": result.final_url,
        "captured_at": format_utc(now_utc()),
        "status": result.status,
        "http_status": result.status,
        "headers": {
            key: value
            for key, value in {
                "etag": result.etag,
                "last_modified": result.last_modified,
            }.items()
            if value is not None
        },
        "safe_response_headers": {
            key: value
            for key, value in {
                "etag": result.etag,
                "last-modified": result.last_modified,
            }.items()
            if value is not None
        },
        "sha256": "sha256:" + hashlib.sha256(result.body).hexdigest(),
        "bytes": len(result.body),
        "raw_item_count": result.body.lower().count(b"<item"),
        "content_encoding": None,
        "parser_expectations": {"surface": feed.surface},
    }
    target.write_bytes(result.body)
    try:
        sidecar.write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf8",
        )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {
        **plan,
        "dry_run": False,
        "bytes": len(result.body),
        "sha256": metadata["sha256"],
    }
