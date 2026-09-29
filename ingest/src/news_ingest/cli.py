"""Agent-facing command line interface with a stable JSON envelope."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .collect import collect_once
from .config import ConfigError, config_hash, load_config
from .db import RebuildError
from .export import export_bundle, plan_export
from .fixture import capture_fixture
from .health import health
from .http import HttpError
from .replay import backup, rebuild_articles, restore_check

SCHEMA_VERSION = "2.0"
REPOSITORY_ROOT = Path(__file__).parents[2]


class CLIUsageError(Exception):
    def __init__(self, action: str, message: str, usage: str):
        super().__init__(message)
        self.action = action
        self.usage = usage


class ActionError(Exception):
    def __init__(
        self,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


class JSONArgumentParser(argparse.ArgumentParser):
    """Turn argparse failures into the CLI's JSON error contract."""

    def error(self, message: str) -> None:  # type: ignore[override]
        action = self.prog.rsplit(" ", 1)[-1] if " " in self.prog else "unknown"
        raise CLIUsageError(action, message, self.format_usage().strip())


def _meta() -> dict[str, str]:
    return {"schema_version": SCHEMA_VERSION, "cli_version": __version__}


def _ok(action: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "action": action, "result": result, "meta": _meta()}


def _fail(
    action: str,
    error_type: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "error": {"type": error_type, "message": message, "details": details or {}},
        "meta": _meta(),
    }


def _emit(envelope: dict[str, Any]) -> None:
    print(
        json.dumps(
            envelope,
            ensure_ascii=False,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


CONFIG_PARAM = {
    "name": "config",
    "type": "string",
    "required": False,
    "default": "config/sources.yaml",
}
SOURCE_PARAM = {"name": "source", "type": "string", "required": False}
DRY_RUN_PARAM = {
    "name": "dry_run",
    "type": "boolean",
    "required": False,
    "default": False,
}

ACTIONS: dict[str, dict[str, Any]] = {
    "benchmark-collect": {
        "description": "Compare indexed and unindexed ingestion on disposable synthetic history.",
        "mutates": False,
        "network": False,
        "params": [],
    },
    "backup": {
        "description": "Create a new SQLite backup file; refuses to overwrite.",
        "mutates": True,
        "network": False,
        "params": [
            CONFIG_PARAM,
            {"name": "output", "type": "string", "required": True},
            DRY_RUN_PARAM,
        ],
    },
    "capture-fixture": {
        "description": "Capture one configured RSS feed and a secret-free metadata sidecar.",
        "mutates": True,
        "network": True,
        "params": [
            CONFIG_PARAM,
            {"name": "feed_id", "type": "string", "required": True},
            {"name": "output", "type": "string", "required": True},
            DRY_RUN_PARAM,
        ],
    },
    "check": {
        "description": "Run the complete network-free repository verification suite.",
        "mutates": False,
        "network": False,
        "params": [CONFIG_PARAM],
    },
    "collect": {
        "description": "Poll configured first-party RSS feeds once and commit valid observations.",
        "mutates": True,
        "network": True,
        "params": [
            CONFIG_PARAM,
            SOURCE_PARAM,
            {"name": "once", "type": "boolean", "required": True},
            DRY_RUN_PARAM,
        ],
    },
    "enrich": {
        "description": "Report article enrichment as disabled in release 1.",
        "mutates": False,
        "network": False,
        "availability": "disabled_release_1",
        "params": [CONFIG_PARAM, SOURCE_PARAM],
    },
    "export": {
        "description": "Publish an immutable deterministic JSONL export bundle.",
        "mutates": True,
        "network": False,
        "params": [
            CONFIG_PARAM,
            {"name": "since", "type": "string", "required": False},
            {"name": "until", "type": "string", "required": False},
            {"name": "changed_since", "type": "string", "required": False},
            {
                "name": "format",
                "type": "string",
                "required": False,
                "default": "jsonl",
                "enum": ["jsonl"],
            },
            {"name": "output", "type": "string", "required": True},
            DRY_RUN_PARAM,
        ],
    },
    "health": {
        "description": "Read database integrity and per-feed collection health.",
        "mutates": False,
        "network": False,
        "params": [CONFIG_PARAM],
    },
    "list-actions": {
        "description": "Return the machine-readable action and parameter catalog.",
        "mutates": False,
        "network": False,
        "params": [],
    },
    "live-contracts": {
        "description": "Report live source contracts as disabled in release 1.",
        "mutates": False,
        "network": False,
        "availability": "disabled_release_1",
        "params": [CONFIG_PARAM, SOURCE_PARAM],
    },
    "rebuild-articles": {
        "description": "Compare or rebuild the article projection from retained sightings.",
        "mutates": True,
        "network": False,
        "params": [CONFIG_PARAM, SOURCE_PARAM, DRY_RUN_PARAM],
    },
    "replay-payloads": {
        "description": "Report raw-payload replay as disabled in release 1.",
        "mutates": False,
        "network": False,
        "availability": "disabled_release_1",
        "params": [
            CONFIG_PARAM,
            SOURCE_PARAM,
            {"name": "since", "type": "string", "required": True},
        ],
    },
    "restore-check": {
        "description": "Check the integrity of a SQLite backup without changing the live database.",
        "mutates": False,
        "network": False,
        "params": [{"name": "backup", "type": "string", "required": True}],
    },
    "snapshot-homepages": {
        "description": "Report HTML homepage capture as disabled in release 1.",
        "mutates": False,
        "network": False,
        "availability": "disabled_release_1",
        "params": [CONFIG_PARAM, SOURCE_PARAM],
    },
    "validate-config": {
        "description": "Validate configuration without changing state or making network requests.",
        "mutates": False,
        "network": False,
        "params": [CONFIG_PARAM],
    },
    "version": {
        "description": "Return CLI and output-schema versions.",
        "mutates": False,
        "network": False,
        "params": [],
    },
}


def _add_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="config/sources.yaml")


def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source")


def _command(subparsers: Any, name: str, example: str) -> argparse.ArgumentParser:
    info = ACTIONS[name]
    return subparsers.add_parser(
        name,
        help=info["description"],
        description=info["description"],
        epilog=f"Example: {example}",
    )


def build_parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(
        prog="gather_news.sh",
        description="Collect, inspect, back up, and export news through a JSON agent API.",
    )
    parser.add_argument("--version", action="store_true", help="Return version information as JSON")
    sub = parser.add_subparsers(dest="cmd", parser_class=JSONArgumentParser)

    _command(sub, "list-actions", "./gather_news.sh list-actions")
    _command(sub, "benchmark-collect", "./gather_news.sh benchmark-collect")

    p = _command(sub, "validate-config", "./gather_news.sh validate-config")
    _add_config(p)

    p = _command(sub, "collect", "./gather_news.sh collect --once")
    _add_config(p)
    _add_source(p)
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")

    p = _command(sub, "health", "./gather_news.sh health")
    _add_config(p)

    p = _command(
        sub,
        "export",
        "./gather_news.sh export --since 2026-09-07T00:00:00Z "
        "--until 2026-09-08T00:00:00Z --output exports/2026-09-07 --dry-run",
    )
    _add_config(p)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--since")
    mode.add_argument("--changed-since")
    p.add_argument("--until")
    p.add_argument("--format", choices=("jsonl",), default="jsonl")
    p.add_argument("--output", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = _command(
        sub,
        "backup",
        "./gather_news.sh backup --output backups/news.sqlite3 --dry-run",
    )
    _add_config(p)
    p.add_argument("--output", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = _command(
        sub,
        "restore-check",
        "./gather_news.sh restore-check --backup backups/news.sqlite3",
    )
    p.add_argument("--backup", required=True)

    p = _command(
        sub,
        "rebuild-articles",
        "./gather_news.sh rebuild-articles --dry-run",
    )
    _add_config(p)
    _add_source(p)
    p.add_argument("--dry-run", action="store_true")

    p = _command(
        sub,
        "capture-fixture",
        "./gather_news.sh capture-fixture --feed-id dr.latest "
        "--output tests/fixtures/dr/latest.xml --dry-run",
    )
    _add_config(p)
    p.add_argument("--feed-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = _command(sub, "check", "./gather_news.sh check")
    _add_config(p)

    for name in ("replay-payloads", "live-contracts", "enrich", "snapshot-homepages"):
        p = _command(sub, name, f"./gather_news.sh {name}")
        _add_config(p)
        _add_source(p)
        if name == "replay-payloads":
            p.add_argument("--since", required=True)
        if name == "enrich":
            p.add_argument("--missing-description", action="store_true")
            p.add_argument("--limit", type=int)

    return parser


def _validate_source(config: Any, source: str | None, include_disabled: bool = False) -> None:
    if source is None:
        return
    valid = sorted(config.sources if include_disabled else config.enabled_sources())
    if source not in valid:
        raise ActionError(
            "invalid_arguments",
            f"Unavailable --source '{source}'. Choose one of: {', '.join(valid)}.",
            {"parameter": "source", "value": source, "valid_values": valid},
        )


def _list_actions() -> dict[str, Any]:
    return {
        "actions": [
            {"name": name, **ACTIONS[name]} for name in sorted(ACTIONS) if name != "version"
        ]
    }


def _validate_target(output: str) -> Path:
    target = Path(output)
    if target.exists():
        raise ActionError(
            "conflict",
            f"Target already exists: {output}. Choose a new path; existing outputs are immutable.",
            {"parameter": "output", "path": str(target)},
        )
    parent = target.parent
    if not parent.exists():
        raise ActionError(
            "resource_not_found",
            f"Output parent does not exist: {parent}. Create it, then retry.",
            {"parameter": "output", "parent": str(parent)},
        )
    return target


def _require_database(path: str) -> Path:
    database = Path(path)
    if not database.is_file():
        raise ActionError(
            "resource_not_found",
            f"Database does not exist: {database}. Run collect --once first.",
            {"path": str(database), "next_action": "collect"},
        )
    return database


def _run_checks(config_path: str) -> dict[str, Any]:
    load_config(config_path)
    commands = [
        ("ruff_check", [sys.executable, "-m", "ruff", "check", "."]),
        ("ruff_format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests"]),
        ("pytest", [sys.executable, "-m", "pytest", "-m", "not live", "-q"]),
        ("wrapper_syntax", ["/bin/sh", "-n", "gather_news.sh"]),
    ]
    steps = [{"name": "validate_config", "status": "passed"}]
    for name, command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ActionError(
                "timeout",
                f"Verification step '{name}' exceeded 300 seconds. "
                "Retry once or run the step manually for diagnosis.",
                {"step": name, "timeout_seconds": 300},
            ) from exc
        if completed.returncode:
            details = {
                "step": name,
                "exit_code": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
            raise ActionError(
                "validation_failed",
                f"Verification step '{name}' failed. "
                "Inspect error.details and fix it before retrying.",
                details,
            )
        steps.append({"name": name, "status": "passed"})
    return {"status": "passed", "steps": steps}


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    action = args.cmd
    if action == "list-actions":
        return _list_actions()
    if action == "benchmark-collect":
        from .db import benchmark_sightings

        return benchmark_sightings()
    if action == "restore-check":
        path = Path(args.backup)
        if not path.is_file():
            raise ActionError(
                "resource_not_found",
                f"Backup file does not exist: {path}. Check --backup and retry.",
                {"parameter": "backup", "path": str(path)},
            )
        return restore_check(path)

    config = load_config(args.config)
    source = getattr(args, "source", None)
    _validate_source(config, source, include_disabled=action == "rebuild-articles")

    if action == "validate-config":
        return {
            "config_hash": config_hash(config),
            "enabled_sources": sorted(config.enabled_sources()),
            "enabled_feed_ids": sorted(x[2].id for x in config.enabled_feeds()),
        }
    if action == "collect":
        if not args.once:
            raise ActionError(
                "invalid_arguments",
                "--once is required. Continuous looping is not implemented; "
                "schedule repeated one-shot calls externally.",
                {"missing": ["once"]},
            )
        if args.dry_run:
            feeds = [x[2].id for x in config.enabled_feeds(source)]
            return {
                "dry_run": True,
                "source": source,
                "planned_feed_ids": feeds,
                "planned": len(feeds),
            }
        result = asyncio.run(collect_once(config, source))
        if result["status"] == "failed":
            raise ActionError(
                "upstream_error",
                "Every planned feed failed. Inspect health and stderr diagnostics before retrying.",
                result,
            )
        return result
    if action == "health":
        database = _require_database(config.database_path)
        return health(database, config.failure_alert_threshold)
    if action == "export":
        _validate_target(args.output)
        database = _require_database(config.database_path)
        plan = plan_export(args.output, args.since, args.until, args.changed_since)
        if args.dry_run:
            return {"dry_run": True, **plan}
        return export_bundle(
            database,
            args.output,
            args.since,
            args.until,
            args.changed_since,
        )
    if action == "backup":
        target = _validate_target(args.output)
        database = _require_database(config.database_path)
        if args.dry_run:
            return {"dry_run": True, "database": str(database), "output": str(target)}
        backup(database, target)
        return {"backup": str(target)}
    if action == "rebuild-articles":
        database = _require_database(config.database_path)
        priorities = {
            feed.id: (feed.description_priority, feed.order)
            for sc in config.sources.values()
            for feed in sc.feeds
        }
        return rebuild_articles(
            database, source, args.dry_run, priorities=priorities, lock_path=config.lock_path
        )
    if action == "capture-fixture":
        return asyncio.run(capture_fixture(config, args.feed_id, args.output, dry_run=args.dry_run))
    if action == "check":
        return _run_checks(args.config)
    return {"status": "disabled", "reason": "disabled in release 1"}


def _map_exception(exc: Exception) -> tuple[str, str, dict[str, Any]]:
    if isinstance(exc, RebuildError):
        return exc.code, str(exc), exc.details
    if isinstance(exc, ActionError):
        return exc.error_type, str(exc), exc.details
    if isinstance(exc, ConfigError):
        return (
            "invalid_arguments",
            f"Configuration is invalid: {exc}. Fix --config and retry.",
            {"parameter": "config"},
        )
    if isinstance(exc, FileNotFoundError):
        return "resource_not_found", f"Required file was not found: {exc.filename or exc}.", {}
    if isinstance(exc, PermissionError):
        return "permission_denied", f"Permission denied: {exc.filename or exc}.", {}
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout", "The operation timed out. It is safe to retry once.", {}
    if isinstance(exc, HttpError):
        return (
            "upstream_error",
            "The publisher feed request failed. Inspect health and retry only if transient.",
            {"reason": str(exc)},
        )
    if isinstance(exc, ValueError):
        if "already exists" in str(exc):
            return "conflict", f"The requested target already exists: {exc}.", {}
        return (
            "invalid_arguments",
            f"Invalid request: {exc}. Fix the named arguments and retry.",
            {},
        )
    if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
        return "lock_busy", "The database is busy. Retry after the active writer finishes.", {}
    if isinstance(exc, RuntimeError) and str(exc) == "lock_busy":
        return "lock_busy", "Another writer holds the process lock. Retry later.", {}
    return (
        "internal_error",
        (
            "The command failed unexpectedly. Retry once; if it repeats, "
            "report error.details.exception."
        ),
        {"exception": type(exc).__name__},
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CLIUsageError as exc:
        _emit(
            _fail(
                exc.action,
                "invalid_arguments",
                f"{exc}. Run list-actions or the action's --help and retry.",
                {"usage": exc.usage, "known_actions": sorted(ACTIONS)},
            )
        )
        return 2

    if args.version:
        if args.cmd:
            _emit(
                _fail(
                    args.cmd,
                    "invalid_arguments",
                    "--version cannot be combined with an action.",
                    {"parameter": "version"},
                )
            )
            return 2
        _emit(
            _ok(
                "version",
                {
                    "name": "news-ingest",
                    "version": __version__,
                    "schema_version": SCHEMA_VERSION,
                },
            )
        )
        return 0
    if not args.cmd:
        _emit(
            _fail(
                "unknown",
                "invalid_arguments",
                "No action specified. Run list-actions to see available actions.",
                {"known_actions": sorted(ACTIONS)},
            )
        )
        return 2

    try:
        _emit(_ok(args.cmd, _dispatch(args)))
        return 0
    except Exception as exc:  # noqa: BLE001 -- JSON is the public exception boundary.
        error_type, message, details = _map_exception(exc)
        _emit(_fail(args.cmd, error_type, message, details))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
