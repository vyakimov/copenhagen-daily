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
from .paths import POLICY_PATH, REPO, RUNS, VAR
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


@action("check-clusters")
def check_clusters_action(args: argparse.Namespace) -> dict[str, Any]:
    from .clusters import check_clusters, write_checked

    run_dir = _run_dir(args.run)
    window_doc = _read(run_dir / "window.json", "window.json")
    clusters = _read(run_dir / "clusters.json", "clusters.json")
    checked = check_clusters(clusters, window_doc)
    path = write_checked(checked, run_dir)
    return {
        "checked": str(path),
        "clusters": len(checked["clusters"]),
        "split": sum(1 for c in checked["clusters"] if "split" in c["flags"]),
        "dissolved": sum(1 for c in checked["clusters"] if "too_large" in c["flags"]),
        "removed": sum(len(c["removed"]) for c in checked["clusters"]),
        "singletons": len(checked["singletons"]),
    }


@action("score")
def score_action(args: argparse.Namespace) -> dict[str, Any]:
    from .score import rank, write_ranking

    policy = _policy()
    run_dir = _run_dir(args.run)
    window_doc = _read(run_dir / "window.json", "window.json")
    memory_doc = _read(run_dir / "memory.json", "memory.json")
    checked = _read(run_dir / "clusters-checked.json", "clusters-checked.json")
    ranking = rank(checked, window_doc, memory_doc, policy)
    path = write_ranking(ranking, run_dir)
    decisions: dict[str, int] = {}
    for c in ranking["candidates"]:
        decisions[c["decision"]] = decisions.get(c["decision"], 0) + 1
    return {
        "ranking": str(path),
        "candidates": len(ranking["candidates"]),
        "eligible": decisions.get("eligible", 0),
        "decisions": decisions,
        "diversity_notes": ranking["diversity_notes"],
        "top": [{"rank": c["rank"], "id": c["id"], "score": c["score"]} for c in ranking["candidates"][:5]],
    }


@action("build")
def build_action(args: argparse.Namespace) -> dict[str, Any]:
    from .build import BuildError, build_edition, write_edition

    policy = _policy()
    run_dir = _run_dir(args.run)
    spec_path = Path(args.spec) if args.spec else run_dir / "spec.json"
    output = Path(args.output) if args.output else run_dir / "edition.json"
    spec = _read(spec_path, "spec.json")
    window_doc = _read(run_dir / "window.json", "window.json") if (run_dir / "window.json").is_file() else None
    memory_doc = _read(run_dir / "memory.json", "memory.json") if (run_dir / "memory.json").is_file() else None
    bundle_path = Path(spec["bundle"]) if spec.get("bundle") else Path(window_doc["bundle"]["path"]) if window_doc else None
    if bundle_path is None:
        raise ActionError("invalid_arguments", "the spec names no bundle and the run has no window.json")
    if not bundle_path.is_absolute():
        bundle_path = (REPO / bundle_path) if (REPO / bundle_path).exists() else bundle_path
    feeds_path = Path(spec["feeds"]) if spec.get("feeds") else run_dir / "feeds.json"
    if not feeds_path.is_absolute():
        feeds_path = (REPO / feeds_path) if (REPO / feeds_path).exists() else feeds_path
    try:
        bundle = load_bundle(bundle_path)
    except BundleError as exc:
        raise ActionError("bundle_invalid", str(exc), {"path": str(bundle_path)}) from exc
    feeds = _read(feeds_path, "feeds.json")
    try:
        edition = build_edition(
            spec, bundle, feeds, window=window_doc, memory=memory_doc,
            scoring=set(policy.scoring_publishers), corroborating=set(policy.corroborating_publishers),
        )
    except BuildError as exc:
        raise ActionError("spec_invalid", str(exc), {"spec": str(spec_path)}) from exc
    write_edition(edition, output)
    return {
        "edition": str(output),
        "edition_id": edition["edition"]["id"],
        "stories": len(edition["stories"]),
        "sources": sum(len(s["sources"]) for s in edition["stories"]),
        "coverage": edition["coverage"]["status"],
    }


@action("apply-verdicts")
def apply_verdicts_action(args: argparse.Namespace) -> dict[str, Any]:
    from .contract import validate_edition
    from .verdicts import apply_verdicts

    policy = _policy()
    run_dir = _run_dir(args.run)
    edition_path = Path(args.edition) if args.edition else run_dir / "edition.json"
    verdicts_path = Path(args.verdicts) if args.verdicts else run_dir / "verdicts.json"
    edition = _read(edition_path, "edition.json")
    verdicts = _read(verdicts_path, "verdicts.json")
    if verdicts.get("edition_id") != edition["edition"]["id"]:
        raise ActionError("conflict", "verdicts name a different edition", {"verdicts": verdicts.get("edition_id"), "edition": edition["edition"]["id"]})
    try:
        result = apply_verdicts(edition, verdicts, min_words=policy.limits.story_stands_min_words, final=args.final)
    except ValueError as exc:
        raise ActionError("verdicts_invalid", str(exc)) from exc
    problems = validate_edition(result["edition"])
    if problems:
        raise ActionError("contract_invalid", "the struck edition fails the contract", {"problems": problems[:10]})
    output = Path(args.output) if args.output else run_dir / "edition-checked.json"
    output.write_text(json.dumps(result["edition"], ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    send_back_path = run_dir / "send-back.json"
    send_back_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "edition_id": edition["edition"]["id"],
                "send_back": result["send_back"],
                "fallen": result["fallen"],
                "stories": {sid: r for sid, r in result["stories"].items() if not r["stands"]},
                "strikes": [
                    {"story": s["id"], **v}
                    for s in verdicts["stories"]
                    for v in s["sentences"]
                    if v["verdict"] == "unsupported"
                ],
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf8",
    )
    return {
        "edition": str(output),
        "struck": result["struck"],
        "checked_stories": len(result["stories"]),
        "send_back": result["send_back"],
        "fallen": result["fallen"],
        "guideline_notes": sum(len(r["guideline_notes"]) for r in result["stories"].values()),
    }


@action("run")
def run_action(args: argparse.Namespace) -> dict[str, Any]:
    from .run import RunFailure, run_edition

    policy = _policy()
    try:
        status = run_edition(args, policy)
    except RunFailure as exc:
        raise ActionError(exc.error_type, str(exc), exc.details) from exc
    if status["outcome"] == "failed":
        failure = status["failure"]
        raise ActionError(failure["type"], f"{failure['phase']}: {failure['message']}", {"edition_id": status["edition_id"], "phase": failure["phase"], **failure.get("details", {})})
    return {
        "edition_id": status["edition_id"],
        "outcome": status["outcome"],
        "phases": [p["name"] for p in status["phases"]],
        "published": status.get("published"),
        "elapsed_s": status.get("elapsed_s"),
    }
