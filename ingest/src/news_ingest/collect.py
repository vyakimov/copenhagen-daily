from __future__ import annotations

import asyncio
import fcntl
from contextlib import contextmanager
from time import perf_counter
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
    started = perf_counter()
    timings = {"fetch": 0.0, "parse": 0.0, "database": 0.0}
    counts = {
        "sightings_inserted": 0,
        "historical_rows_read": 0,
        "merge_state_rows_read": 0,
        "merge_state_bootstraps": 0,
    }
    with process_lock(config.lock_path):
        database_started = perf_counter()
        db = Database(config.database_path)
        run = db.start_run(source)
        planned = config.enabled_feeds(source)
        polls = []
        try:
            for sid, sc, feed in planned:
                polls.append(
                    (sid, sc, feed, db.preallocate_poll(run, feed.id, sid, db.state(feed.id)))
                )
            timings["database"] += perf_counter() - database_started
            fetch_started = perf_counter()
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
            timings["fetch"] = perf_counter() - fetch_started
            successes = failures = 0
            priorities = {
                feed.id: (feed.description_priority, feed.order)
                for sc in config.sources.values()
                for feed in sc.feeds
            }
            for (sid, sc, feed, poll), reply in zip(polls, replies):
                try:
                    if isinstance(reply, Exception):
                        raise reply
                    if reply.status == 304:
                        database_started = perf_counter()
                        try:
                            db.commit_not_modified(poll, feed.id, sid, str(feed.url))
                        finally:
                            timings["database"] += perf_counter() - database_started
                    else:
                        parse_started = perf_counter()
                        try:
                            parsed = parse_feed(reply.body, feed, now_utc(), sid, sc)
                        finally:
                            timings["parse"] += perf_counter() - parse_started
                        database_started = perf_counter()
                        try:
                            committed = db.ingest(
                                poll,
                                feed.id,
                                sid,
                                str(feed.url),
                                reply,
                                parsed,
                                priorities,
                                feed.surface,
                            )
                        finally:
                            timings["database"] += perf_counter() - database_started
                        for key in counts:
                            counts[key] += committed[key]
                    successes += 1
                except Exception as exc:  # noqa: BLE001 -- individual publisher isolation.
                    database_started = perf_counter()
                    try:
                        db.fail_poll(poll, exc, feed.id, sid, str(feed.url))
                    finally:
                        timings["database"] += perf_counter() - database_started
                    failures += 1
            status = "success" if not failures else "partial" if successes else "failed"
            result = {
                "run_id": run,
                "succeeded": successes,
                "failed": failures,
                "planned": len(planned),
                "timings_seconds": {
                    **{key: round(value, 6) for key, value in timings.items()},
                    "total": round(perf_counter() - started, 6),
                },
                **counts,
            }
            db.finish_run(run, status, result, ["partial_failures"] if failures else [])
            return {"status": status, **result}
        finally:
            db.close()
