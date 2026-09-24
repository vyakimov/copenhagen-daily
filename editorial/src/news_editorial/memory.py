"""What the paper has already published: covered articles, threads, and the edition clock."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .policy import Policy

SCHEMA_VERSION = 1


def _date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def load_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "threads": []}
    return json.loads(path.read_text(encoding="utf8"))


def save_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf8")
    tmp.replace(path)


def activated_editions(publish_root: Path) -> list[dict[str, Any]]:
    """Activation records, newest sequence first, with the stored edition attached."""
    records = []
    activations = publish_root / "state" / "activations"
    if not activations.is_dir():
        return []
    for path in activations.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf8"))
        if not record.get("activated"):
            continue
        edition_path = publish_root / "store" / "n" / record["edition_id"] / "edition.json"
        if not edition_path.is_file():
            continue
        records.append({"activation": record, "edition": json.loads(edition_path.read_text(encoding="utf8"))})
    records.sort(key=lambda r: r["activation"]["sequence"], reverse=True)
    return records


def build_memory(publish_root: Path, registry_path: Path, policy: Policy, cutoff: str) -> dict[str, Any]:
    registry = load_registry(registry_path)
    story_thread = {sid: t["id"] for t in registry["threads"] for sid in t["story_ids"]}
    records = activated_editions(publish_root)[: policy.schedule.memory_editions]
    editions = []
    covered: dict[str, dict[str, str]] = {}
    for record in records:
        edition = record["edition"]
        stories = []
        for story in edition["stories"]:
            sources = [{"source": s["source"], "source_id": s["source_id"]} for s in story["sources"]]
            stories.append(
                {
                    "id": story["id"],
                    "role": story["role"],
                    "kicker": story["kicker"],
                    "headline": story["copy"]["headline"],
                    "sources": sources,
                    "thread": story_thread.get(story["id"]),
                }
            )
            for s in sources:
                covered.setdefault(f"{s['source']}:{s['source_id']}", {"edition_id": edition["edition"]["id"], "story_id": story["id"]})
        editions.append(
            {
                "id": edition["edition"]["id"],
                "number": edition["edition"]["number"],
                "date": edition["edition"]["date"],
                "cutoff_at": edition["edition"]["cutoff_at"],
                "activated_at": record["activation"]["activated_at"],
                "sequence": record["activation"]["sequence"],
                "stories": stories,
            }
        )
    edition_ids = [e["id"] for e in editions]
    cutoff_date = _date(cutoff)
    active, dormant = [], []
    for thread in sorted(registry["threads"], key=lambda t: t["last_seen_date"], reverse=True):
        row = dict(thread)
        last = thread.get("last_edition_id")
        row["editions_since_published"] = edition_ids.index(last) + 1 if last in edition_ids else None
        age = (cutoff_date - dt.date.fromisoformat(thread["last_seen_date"])).days
        (dormant if age > policy.schedule.thread_dormant_days else active).append(row)
    all_numbers = [r["edition"]["edition"]["number"] for r in activated_editions(publish_root)]
    return {
        "schema_version": SCHEMA_VERSION,
        "publish_root": str(publish_root),
        "cutoff_at": cutoff,
        "previous_cutoff_at": editions[0]["cutoff_at"] if editions else None,
        "next_edition_number": (max(all_numbers) + 1) if all_numbers else 1,
        "editions": editions,
        "covered": covered,
        "threads": active,
        "dormant_threads": dormant,
    }


def write_memory(memory: dict[str, Any], run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "memory.json"
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return path
