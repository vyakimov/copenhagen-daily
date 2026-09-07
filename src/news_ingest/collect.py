from __future__ import annotations

import asyncio
import fcntl
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx

from .config import AppConfig
from .db import Database
from .feed import parse_feed
from .http import fetch
from .time import now_utc


@contextmanager
def process_lock(path):
    import pathlib

    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 -- lifetime spans the yielded lock.
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("lock_busy")
        yield
    finally:
        handle.close()


async def collect_once(config: AppConfig, source: str | None = None) -> dict:
    db = Database(config.database_path)
    run = db.start_run(source)
    planned = config.enabled_feeds(source)
    polls = []
    try:
        with process_lock(config.lock_path):
            for sid, sc, feed in planned:
                polls.append(
                    (sid, sc, feed, db.preallocate_poll(run, feed.id, sid, db.state(feed.id)))
                )
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            timeout = httpx.Timeout(config.http.timeout_seconds)
            async with httpx.AsyncClient(
                http2=True, follow_redirects=True, limits=limits, timeout=timeout
            ) as client:
                host_limits: dict[str, asyncio.Semaphore] = {}

                async def bounded_fetch(feed):
                    host = urlsplit(str(feed.url)).netloc.lower()
                    semaphore = host_limits.setdefault(
                        host, asyncio.Semaphore(config.http.max_connections_per_host)
                    )
                    async with semaphore:
                        return await fetch(
                            client,
                            str(feed.url),
                            db.state(feed.id),
                            config.http,
                            config.max_response_bytes,
                        )

                tasks = [bounded_fetch(feed) for _, _, feed, _ in polls]
                replies = await asyncio.gather(*tasks, return_exceptions=True)
            successes = failures = 0
            priorities = {
                feed.id: (feed.description_priority, feed.order)
                for _, _, feed in config.enabled_feeds()
            }
            for (sid, sc, feed, poll), reply in zip(polls, replies):
                try:
                    if isinstance(reply, Exception):
                        raise reply
                    if reply.status == 304:
                        db.commit_not_modified(poll, feed.id, sid, str(feed.url))
                    else:
                        db.ingest(
                            poll,
                            feed.id,
                            sid,
                            str(feed.url),
                            reply,
                            parse_feed(reply.body, feed, now_utc(), sid, sc),
                            priorities,
                            feed.surface,
                        )
                    successes += 1
                except Exception as exc:  # noqa: BLE001 -- individual publisher isolation.
                    db.fail_poll(poll, exc)
                    failures += 1
            status = "success" if not failures else "partial" if successes else "failed"
            result = {
                "run_id": run,
                "succeeded": successes,
                "failed": failures,
                "planned": len(planned),
            }
            db.finish_run(run, status, result, ["partial_failures"] if failures else [])
            return {"status": status, **result}
    finally:
        db.close()
