"""The numbered candidate window the editor reads: sections, status, prominence, and clocks attached."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .bundle import Bundle
from .policy import Policy
from .wire import wire_agency

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
        # A mixed feed maps to nothing and the publisher's own category tags say the section instead.
        by_category = policy.category_sections.get(article["source"], {})
        for category in article.get("categories") or []:
            for section in by_category.get(category, []):
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
                "wire": wire_agency(article, policy.wire_agencies),
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


DESCRIPTION_CHARS = 500
DUPLICATE_DESCRIPTION_MIN_CHARS = 80
_SENTENCE_END = re.compile(r"[.!?…»\"]\s")


def _cut(description: str, limit: int = DESCRIPTION_CHARS) -> str:
    """The description for the reading view: whole when short, else cut at the last sentence end
    before the limit, with an ellipsis so the reader knows window.json holds the rest."""
    if len(description) <= limit:
        return description
    head = description[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    cut = ends[-1] if ends and ends[-1] >= limit // 2 else (head.rfind(" ") if head.rfind(" ") > 0 else limit)
    return head[:cut].rstrip() + " …"


def _title_key(article: dict[str, Any]) -> str:
    return " ".join(article["title"].lower().split())


def _description_key(article: dict[str, Any]) -> str | None:
    description = " ".join((article.get("description") or "").split())
    return description.lower() if len(description) >= DUPLICATE_DESCRIPTION_MIN_CHARS else None


def _listing(groups: dict[str, list[dict[str, Any]]], full_since: str) -> list[str]:
    """One publisher after another, each article on its line. The same text carried twice, by one
    outlet's several feeds or by several outlets running the same wire copy, is listed once; later
    copies point at the first by number so the editor clusters them without reading them again. The
    same headline over a different description is not the same text: it keeps its description and
    only says where the headline was seen first, so a rolling page's updates are not hidden."""
    lines: list[str] = []
    by_text: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    for source in sorted(groups):
        rows = groups[source]
        status = rows[0]["status"]
        lines.append(f"## {source} ({status}, {len(rows)})")
        lines.append("")
        for a in rows:
            sections = ",".join(a["sections"]) or "-"
            flags = " opinion" if a["opinion"] else ""
            if a.get("wire"):
                flags += f" wire:{a['wire']}"
            head = f"- [{a['n']}] {a['published_at'][:16]} {sections}{flags}: "
            shown = status != "linked" and a["published_at"] >= full_since and bool(a["description"])
            text_key, title_key = _description_key(a), _title_key(a)
            twin = by_text.get(text_key) if text_key else None
            if twin is None and not shown:
                # Nothing but the headline would be shown, and the headline is already on the page.
                twin = by_title.get(title_key)
            if twin is not None:
                lines.append(f"{head}same text as [{twin['n']}] {twin['source']}")
                continue
            if text_key:
                by_text.setdefault(text_key, a)
            seen_title = by_title.get(title_key)
            by_title.setdefault(title_key, a)
            note = f" (same headline as [{seen_title['n']}] {seen_title['source']})" if seen_title is not None else ""
            lines.append(head + a["title"] + note)
            if shown:
                lines.append(f"  {_cut(a['description'])}")
        lines.append("")
    return lines


def _reading_views(window: dict[str, Any]) -> tuple[str, str]:
    """Two Markdown views. The main one holds the Danish scoring and corroborating publishers, whose
    articles can make a story: recent ones with their description, cut at DESCRIPTION_CHARS. The linked
    one holds the foreign outlets by headline; they only ever attach to a story as sources."""
    cutoff = dt.datetime.fromisoformat(window["cutoff_at"].replace("Z", "+00:00"))
    full_since = (cutoff - dt.timedelta(hours=READ_IN_FULL_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    main: dict[str, list[dict[str, Any]]] = defaultdict(list)
    linked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for article in window["articles"]:
        (linked if article["status"] == "linked" else main)[article["source"]].append(article)
    n_main = sum(len(v) for v in main.values())
    n_linked = sum(len(v) for v in linked.values())
    main_lines = [
        f"# Candidate window to {window['cutoff_at']}",
        "",
        f"{len(window['articles'])} articles in the window. This file lists the {n_main} from Danish scoring and",
        f"corroborating publishers; the {n_linked} from linked publishers are headlines in window-linked.md.",
        f"Danish articles from the last {READ_IN_FULL_HOURS} hours carry their description, cut at about",
        f"{DESCRIPTION_CHARS} characters where an ellipsis marks the cut and window.json has the rest.",
        "Refer to articles by number. An article flagged wire:<agency> is that agency's copy, carried by",
        "the outlet it is listed under. A line reading \"same text as [m]\" is the same report carried",
        "again; it belongs with [m]. \"same headline as [m]\" is a headline seen before over a different",
        "description, often a rolling page updated; read it as its own article.",
        "",
        *_listing(main, full_since),
    ]
    linked_lines = [
        f"# Linked publishers, candidate window to {window['cutoff_at']}",
        "",
        f"{n_linked} articles from linked publishers, by headline. They never make a story eligible and",
        "never score; they attach to a cluster as sources when they report the same event. Refer to",
        "articles by number. A line reading \"same text as [m]\" is the same report carried again.",
        "",
        *_listing(linked, full_since),
    ]
    return "\n".join(main_lines), "\n".join(linked_lines)


def write_window(window: dict[str, Any], run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "window.json"
    path.write_text(json.dumps(window, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    main, linked = _reading_views(window)
    (run_dir / "window.md").write_text(main, encoding="utf8")
    (run_dir / "window-linked.md").write_text(linked, encoding="utf8")
    return path
