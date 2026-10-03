"""Wikipedia summaries for the explanations a writer took from its own knowledge.

The runner fetches them, never a session: the one host a run may reach besides delivery is
wikipedia.org, and what comes back is data for the checker, not instructions to anyone.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

HOSTS = {"en": "en.wikipedia.org", "da": "da.wikipedia.org"}
USER_AGENT = "copenhagen-daily/0.1 (newsroom checker; personal newspaper)"


def summary_url(title: str) -> str:
    """The REST summary endpoint for an article title, English unless prefixed `da:`."""
    language = "en"
    if title.startswith("da:"):
        language, title = "da", title[3:]
    title = title.strip().replace(" ", "_")
    return f"https://{HOSTS[language]}/api/rest_v1/page/summary/{urllib.parse.quote(title, safe='')}"


def _fetch(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- host fixed above
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def wikipedia_summary(title: str, timeout: float = 10.0, fetch: Callable[[str, float], tuple[int, bytes]] = _fetch) -> dict[str, Any]:
    """The article's title, extract and URL, or a record of why there is none. Never raises."""
    url = summary_url(title)
    host = urllib.parse.urlparse(url).netloc
    if host not in HOSTS.values():
        return {"requested": title, "status": "refused", "url": url}
    try:
        status, body = fetch(url, timeout)
    except Exception as exc:  # noqa: BLE001 -- a lookup that fails is a missing reference, not a failed run.
        return {"requested": title, "status": "unavailable", "url": url, "error": f"{type(exc).__name__}: {exc}"}
    if status != 200:
        return {"requested": title, "status": "missing" if status == 404 else "unavailable", "url": url, "http_status": status}
    try:
        doc = json.loads(body.decode("utf8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"requested": title, "status": "unavailable", "url": url, "error": f"{type(exc).__name__}: {exc}"}
    extract = (doc.get("extract") or "").strip()
    if not extract:
        return {"requested": title, "status": "missing", "url": url}
    return {
        "requested": title,
        "status": "found",
        "title": doc.get("title") or title,
        "extract": extract,
        "url": (doc.get("content_urls") or {}).get("desktop", {}).get("page") or url,
        "type": doc.get("type"),
    }
