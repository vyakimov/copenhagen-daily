from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from .config import HttpConfig


class HttpError(RuntimeError):
    pass


@dataclass
class FetchResult:
    status: int
    body: bytes
    attempts: int
    final_url: str
    etag: str | None
    last_modified: str | None
    warnings: list[str]


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    state,
    settings: HttpConfig,
    max_bytes: int,
    sleep=asyncio.sleep,
) -> FetchResult:
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9,*/*;q=0.1",
        "User-Agent": settings.user_agent,
    }
    if state and state["etag"]:
        headers["If-None-Match"] = state["etag"]
    if state and state["last_modified"]:
        headers["If-Modified-Since"] = state["last_modified"]
    last = None
    for attempt in range(1, settings.attempts + 1):
        try:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 304:
                    return FetchResult(304, b"", attempt, str(response.url), None, None, [])
                if (
                    response.status_code in {429, 500, 502, 503, 504}
                    and attempt < settings.attempts
                ):
                    retry = response.headers.get("Retry-After")
                    delay = min(60.0, 2 ** (attempt - 1))
                    if retry:
                        try:
                            delay = min(60, float(retry))
                        except ValueError:
                            try:
                                delay = min(
                                    60,
                                    max(
                                        0,
                                        (
                                            parsedate_to_datetime(retry).astimezone(UTC)
                                            - datetime.now(UTC)
                                        ).total_seconds(),
                                    ),
                                )
                            except ValueError:
                                pass
                    await sleep(delay)
                    continue
                if response.status_code >= 400:
                    kind = "blocked" if response.status_code == 403 else "http_error"
                    raise HttpError(f"{kind}: {response.status_code}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise HttpError("response_too_large")
                return FetchResult(
                    response.status_code,
                    bytes(data),
                    attempt,
                    str(response.url),
                    response.headers.get("ETag"),
                    response.headers.get("Last-Modified"),
                    [],
                )
        except (httpx.TransportError, HttpError) as exc:
            last = exc
            if (
                isinstance(exc, HttpError)
                and not str(exc).startswith("http_error")
                and not str(exc).startswith("blocked")
                and attempt < settings.attempts
            ):
                await sleep(min(60, 2 ** (attempt - 1)))
                continue
            if isinstance(exc, httpx.TransportError) and attempt < settings.attempts:
                await sleep(min(60, 2 ** (attempt - 1)))
                continue
            raise HttpError(str(exc)) from exc
    raise HttpError(str(last))
