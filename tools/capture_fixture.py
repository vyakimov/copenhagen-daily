"""Capture one configured RSS feed with a secret-free sidecar; never overwrites."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from news_ingest.config import load_config
from news_ingest.http import fetch
from news_ingest.time import format_utc, now_utc


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("feed_id")
    p.add_argument("destination")
    p.add_argument("--config", default="config/sources.yaml")
    a = p.parse_args()
    out = Path(a.destination)
    if out.exists() or out.with_suffix(out.suffix + ".json").exists():
        raise SystemExit("destination exists")
    c = load_config(a.config)
    matches = [x for x in c.enabled_feeds() if x[2].id == a.feed_id]
    if not matches:
        raise SystemExit("unknown feed")
    _, _, feed = matches[0]
    async with httpx.AsyncClient(follow_redirects=True, http2=True) as client:
        result = await fetch(client, str(feed.url), None, c.http, c.max_response_bytes)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.body)
    safe = {
        k: v for k, v in {"etag": result.etag, "last_modified": result.last_modified}.items() if v
    }
    out.with_suffix(out.suffix + ".json").write_text(
        json.dumps(
            {
                "url": str(feed.url),
                "final_url": result.final_url,
                "captured_at": format_utc(now_utc()),
                "status": result.status,
                "headers": safe,
                "sha256": "sha256:" + hashlib.sha256(result.body).hexdigest(),
                "content_encoding": None,
            }
        )
    )


asyncio.run(main())
