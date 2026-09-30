"""Is the paper really on the site? An outside-in check of the live site against block 3's live tree.

The live tree under the publish root is exactly what delivery syncs, so the check compares bytes:
the latest pointer, the front page, and the edition's manifest. The verdict is one state, and
`fixable` says whether delivering again is the whole remedy."""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

Response = tuple[int, dict[str, str], bytes]
Fetch = Callable[[str], Response]

STATES = ("ok", "run_in_progress", "no_edition_today", "broken", "not_delivered", "unreachable", "no_local_edition")


def http_fetch(url: str) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": "copenhagen-daily-desk/0.1", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, b""


def verify_live(
    publish_root: Path,
    site_url: str,
    fetch: Fetch = http_fetch,
    *,
    today: str,
    run_in_progress: bool = False,
) -> dict[str, Any]:
    site = site_url.rstrip("/")
    live = publish_root / "live"
    report: dict[str, Any] = {
        "site": site, "today": today, "local_edition": None, "live_edition": None, "number": None,
        "date": None, "checks": [], "problems": [], "fixable": False, "state": "ok",
    }
    problems: list[str] = report["problems"]

    def check(name: str, ok: bool, detail: str | None = None) -> None:
        report["checks"].append({"name": name, "ok": ok, **({"detail": detail} if detail else {})})

    def finish(state: str, fixable: bool = False) -> dict[str, Any]:
        report["state"], report["fixable"] = state, fixable
        return report

    pointer = live / "latest.json"
    if not pointer.is_file():
        problems.append("no edition has been published at the publish root")
        return finish("no_local_edition")
    local = json.loads(pointer.read_text(encoding="utf8")).get("web") or {}
    edition_id = local.get("edition_id")
    if not edition_id:
        problems.append("the local latest.json names no web edition")
        return finish("no_local_edition")
    report["local_edition"], report["date"] = edition_id, local.get("date")
    edition_file = live / "n" / edition_id / "edition.json"
    if edition_file.is_file():
        try:
            report["number"] = json.loads(edition_file.read_text(encoding="utf8"))["edition"].get("number")
        except (json.JSONDecodeError, KeyError, TypeError):
            report["number"] = None

    try:
        status, headers, body = fetch(f"{site}/latest.json")
    except Exception as exc:  # noqa: BLE001 -- any transport failure is the same verdict
        problems.append(f"{site}/latest.json could not be fetched: {exc}")
        check("reachable", False, str(exc))
        return finish("unreachable")
    if status != 200:
        problems.append(f"{site}/latest.json returned {status}")
        check("reachable", False, f"HTTP {status}")
        return finish("unreachable")
    check("reachable", True)

    try:
        remote = json.loads(body.decode("utf8")).get("web") or {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        remote = {}
    report["live_edition"] = remote.get("edition_id")
    same_edition = report["live_edition"] == edition_id
    same_bytes = body == pointer.read_bytes()
    check("latest_pointer", same_bytes, None if same_bytes else (f"live {report['live_edition']}, local {edition_id}" if not same_edition else "the live pointer differs from the local one"))
    if not same_edition:
        problems.append(f"the site serves {report['live_edition'] or 'no edition'}; the newsroom has {edition_id}")
        return finish("not_delivered", fixable=True)
    if not same_bytes:
        problems.append("the live latest.json names the same edition but differs from the newsroom's copy")
        return finish("not_delivered", fixable=True)

    robots = "noindex" in headers.get("x-robots-tag", "")
    check("robots_header", robots, None if robots else "x-robots-tag missing on a non-HTML file")

    manifest_ok = _same_bytes(fetch, f"{site}/n/{edition_id}/manifest.json", live / "n" / edition_id / "manifest.json")
    check("manifest", manifest_ok, None if manifest_ok else "the live manifest differs from the local one")
    page_status, _, page = _get(fetch, f"{site}/")
    page_ok = page_status == 200 and page == (live / "index.html").read_bytes()
    check("front_page", page_ok, None if page_ok else f"HTTP {page_status}" if page_status != 200 else "the live front page differs from the local one")
    if not manifest_ok or not page_ok:
        problems.append("the live files differ from the newsroom's copy of the same edition" + ("" if manifest_ok else " (manifest)") + ("" if page_ok else " (front page)"))
        return finish("not_delivered", fixable=True)

    stylesheet = re.search(rb'href="(/a/[^"]+\.css)"', page)
    if stylesheet:
        href = stylesheet.group(1).decode("ascii")
        css_status, _, _ = _get(fetch, f"{site}{href}")
        check("stylesheet", css_status == 200, None if css_status == 200 else f"{href} returned {css_status}")
        if css_status != 200:
            problems.append(f"the stylesheet {href} is missing from the site")
            return finish("broken", fixable=True)
    else:
        check("stylesheet", False, "the front page links no stylesheet")
        problems.append("the front page links no stylesheet")
        return finish("broken")
    if not robots:
        problems.append("the site is not sending x-robots-tag: noindex; check the CloudFront response function")
        return finish("broken")

    if report["date"] and report["date"] < today:
        problems.append(f"the latest edition is dated {report['date']}, not {today}")
        return finish("run_in_progress" if run_in_progress else "no_edition_today")
    return finish("ok")


def _get(fetch: Fetch, url: str) -> Response:
    try:
        return fetch(url)
    except Exception as exc:  # noqa: BLE001
        return 0, {}, str(exc).encode()


def _same_bytes(fetch: Fetch, url: str, local: Path) -> bool:
    if not local.is_file():
        return False
    status, _, body = _get(fetch, url)
    return status == 200 and body == local.read_bytes()


def summary(report: dict[str, Any], fix: dict[str, Any] | None = None) -> tuple[str, str]:
    """The Discord line: a subject and a short body."""
    number = f"No. {report['number']} " if report.get("number") else ""
    edition = f"{number}({report['local_edition']})" if report.get("local_edition") else "no edition"
    state = report["state"]
    lines: list[str] = []
    if state == "ok":
        subject = f"Copenhagen Daily: the paper is live, {edition}"
        lines.append(f"{report['site']} serves {edition}: latest pointer, front page, manifest, stylesheet and robots header all match.")
    else:
        subject = f"Copenhagen Daily: live check {state.replace('_', ' ')}, {edition}"
        lines.extend(report["problems"])
    if fix:
        lines.append(f"Fix applied: {fix['applied']}; state afterwards {fix['after']}.")
    elif report.get("fixable"):
        lines.append("Delivering again would fix this: edit_news.sh deliver, or verify-live --fix.")
    elif state == "no_edition_today":
        lines.append("No run holds the lock. The 07:30 retry will run if the morning run failed; otherwise check status.json.")
    elif state == "run_in_progress":
        lines.append("A run holds the lock; check again later.")
    return subject, "\n".join(lines)
