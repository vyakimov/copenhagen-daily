"""The numbered candidate window the editor reads: sections, status, prominence, and clocks attached."""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .bundle import Bundle
from .policy import Policy

SCHEMA_VERSION = 1
READ_IN_FULL_HOURS = 24


def _ts(value: str) -> str:
    """Normalise block 1's timestamps to the contract's six-fraction-digit form."""
    if "." in value:
        return value
    return value.replace("Z", ".000000Z")


def input_id_for(cutoff: str) -> str:
    when = dt.datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    return f"export-{when:%Y-%m-%d-%H%M}"


def build_window(bundle: Bundle, policy: Policy, cutoff: str, previous_cutoff: str | None) -> dict[str, Any]:
    cutoff = _ts(cutoff)
    surfaces: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for appearance in bundle.appearances:
        surfaces[(appearance["source"], appearance["source_id"])].append(appearance)

    rows = []
    for article in bundle.articles:
        key = (article["source"], article["source_id"])
        seen = surfaces.get(key, [])
        sections: list[str] = []
        for appearance in seen:
            for section in policy.feed_sections.get(appearance["surface_id"], []):
                if section not in sections:
                    sections.append(section)
        opinion = "opinion" in sections
        sections = sorted(s for s in sections if s != "opinion")
        status = policy.publisher_status(article["source"])
        prominence = None
        if status == "scoring":
            ranked = [a for a in seen if a["surface_id"] in policy.ranked_feeds and a.get("prominence_score") is not None]
            if ranked:
                best = max(ranked, key=lambda a: (a["prominence_score"], a["observed_at"]))
                prominence = {"score": best["prominence_score"], "surface": best["surface_id"]}
        first_seen = _ts(article["first_seen_at"])
        rows.append(
            {
                "source": article["source"],
                "source_id": article["source_id"],
                "status": status,
                "title": article["title"],
                "description": article.get("description"),
                "language": article.get("language"),
                "authors": article.get("authors") or [],
                "categories": article.get("categories") or [],
                "content_type": article.get("content_type"),
                "url": article["canonical_url"],
                "published_at": _ts(article["published_at"]),
                "first_seen_at": first_seen,
                "newly_observed": previous_cutoff is None or first_seen > _ts(previous_cutoff),
                "sections": sections,
                "opinion": opinion,
                "feeds": sorted({a["surface_id"] for a in seen}),
                "prominence": prominence,
                "content_hash": article["content_hash"],
            }
        )
    rows.sort(key=lambda r: (r["published_at"], r["source"], r["source_id"]), reverse=True)
    for number, row in enumerate(rows, start=1):
        row["n"] = number
        row_keys = ["n"] + [k for k in row if k != "n"]
        for k in row_keys:
            row[k] = row.pop(k)
    since, until = bundle.window
    return {
        "schema_version": SCHEMA_VERSION,
        "cutoff_at": cutoff,
        "previous_cutoff_at": _ts(previous_cutoff) if previous_cutoff else None,
        "window": {"since": _ts(since), "until": _ts(until)},
        "bundle": {
            "path": str(bundle.path),
            "input_id": input_id_for(cutoff),
            "manifest_sha256": bundle.manifest_sha256,
            "article_count": len(rows),
        },
        "articles": rows,
    }


def _reading_view(window: dict[str, Any]) -> str:
    """A compact Markdown view: recent Danish articles in full, everything else by headline."""
    cutoff = dt.datetime.fromisoformat(window["cutoff_at"].replace("Z", "+00:00"))
    full_since = (cutoff - dt.timedelta(hours=READ_IN_FULL_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    lines = [
        f"# Candidate window to {window['cutoff_at']}",
        "",
        f"{len(window['articles'])} articles. Danish articles from the last {READ_IN_FULL_HOURS} hours carry their",
        "description; every other article is its headline. Refer to articles by number.",
        "",
    ]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in window["articles"]:
        groups[article["source"]].append(article)
    for source in sorted(groups):
        rows = groups[source]
        status = rows[0]["status"]
        lines.append(f"## {source} ({status}, {len(rows)})")
        lines.append("")
        for a in rows:
            sections = ",".join(a["sections"]) or "-"
            flags = " opinion" if a["opinion"] else ""
            lines.append(f"- [{a['n']}] {a['published_at'][:16]} {sections}{flags}: {a['title']}")
            if status != "linked" and a["published_at"] >= full_since and a["description"]:
                lines.append(f"  {a['description']}")
        lines.append("")
    return "\n".join(lines)


def write_window(window: dict[str, Any], run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "window.json"
    path.write_text(json.dumps(window, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    (run_dir / "window.md").write_text(_reading_view(window), encoding="utf8")
    return path
