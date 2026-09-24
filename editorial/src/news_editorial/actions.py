"""Action handlers. Each takes the parsed arguments and returns the `result` object."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

from . import blocks
from .bundle import BundleError, load_bundle
from .cli import ACTIONS, ActionError, action
from .memory import build_memory, write_memory
from .paths import POLICY_PATH, RUNS, VAR
from .policy import Policy, load_policy
from .window import build_window, write_window

THREADS_REGISTRY = VAR / "threads.json"


def _run_dir(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() or path.exists() else RUNS / value


def _policy() -> Policy:
    return load_policy(POLICY_PATH)


def _read(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise ActionError("resource_not_found", f"{what} is missing: {path}", {"path": str(path)})
    return json.loads(path.read_text(encoding="utf8"))


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fmt_ts(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@action("list-actions")
def list_actions(_: argparse.Namespace) -> dict[str, Any]:
    return {"actions": [{"name": name, **spec} for name, spec in sorted(ACTIONS.items())]}


def _feeds_from_health(health: dict[str, Any]) -> list[dict[str, Any]]:
    feeds = []
    for feed in health["feeds"]:
        if feed["last_checked_at"] is None:
            outcome = "not_checked"
        elif feed["consecutive_failures"]:
            outcome = "failed"
        else:
            outcome = "checked"
        feeds.append(
            {
                "feed_id": feed["feed_id"],
                "source": feed["source"],
                "outcome": outcome,
                "last_checked_at": feed["last_checked_at"],
            }
        )
    feeds.sort(key=lambda f: f["feed_id"])
    return feeds


@action("window")
def window(args: argparse.Namespace) -> dict[str, Any]:
    policy = _policy()
    run_dir = _run_dir(args.run)
    run_dir.mkdir(parents=True, exist_ok=True)
    cutoff = _parse_ts(args.cutoff)
    if args.bundle:
        bundle_path = Path(args.bundle)
    else:
        since = cutoff - dt.timedelta(hours=policy.schedule.candidate_window_hours)
        bundle_path = run_dir / "bundle"
        if bundle_path.exists():
            raise ActionError("conflict", f"bundle already exported: {bundle_path}", {"path": str(bundle_path)})
        blocks.ingest("export", "--since", _fmt_ts(since), "--until", _fmt_ts(cutoff), "--output", str(bundle_path))
    try:
        bundle = load_bundle(bundle_path)
    except BundleError as exc:
        raise ActionError("bundle_invalid", str(exc), {"path": str(bundle_path)}) from exc
    if args.feeds:
        feeds = json.loads(Path(args.feeds).read_text(encoding="utf8"))
    else:
        feeds = _feeds_from_health(blocks.ingest("health"))
    (run_dir / "feeds.json").write_text(json.dumps(feeds, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    doc = build_window(bundle, policy, cutoff=_fmt_ts(cutoff), previous_cutoff=args.previous_cutoff)
    path = write_window(doc, run_dir)
    return {
        "run": str(run_dir),
        "window": str(path),
        "bundle": doc["bundle"],
        "article_count": doc["bundle"]["article_count"],
        "feeds": {"count": len(feeds), "failed": sum(1 for f in feeds if f["outcome"] != "checked")},
    }


@action("memory")
def memory(args: argparse.Namespace) -> dict[str, Any]:
    policy = _policy()
    run_dir = _run_dir(args.run)
    window_doc = _read(run_dir / "window.json", "window.json")
    registry = Path(args.registry) if args.registry else THREADS_REGISTRY
    doc = build_memory(Path(args.publish_root), registry, policy, cutoff=window_doc["cutoff_at"])
    path = write_memory(doc, run_dir)
    return {
        "memory": str(path),
        "editions": [e["id"] for e in doc["editions"]],
        "covered_articles": len(doc["covered"]),
        "threads": len(doc["threads"]),
        "dormant_threads": len(doc["dormant_threads"]),
        "next_edition_number": doc["next_edition_number"],
        "previous_cutoff_at": doc["previous_cutoff_at"],
    }


@action("status")
def status(_: argparse.Namespace) -> dict[str, Any]:
    runs = sorted(p for p in RUNS.glob("*") if p.is_dir()) if RUNS.is_dir() else []
    if not runs:
        return {"runs": 0}
    latest = runs[-1]
    status_path = latest / "status.json"
    return {"runs": len(runs), "latest": latest.name, "status": _read(status_path, "status.json") if status_path.is_file() else None}
