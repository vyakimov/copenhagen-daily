"""The desk's command line: one JSON object on stdout, diagnostics on stderr, like the other blocks."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any, Callable

from . import __version__

SCHEMA_VERSION = "1.0"


class ActionError(Exception):
    """A well-formed action that failed; becomes an `ok: false` envelope with exit 1."""

    def __init__(self, error_type: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


class UsageError(Exception):
    pass


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


ACTIONS: dict[str, dict[str, Any]] = {
    "list-actions": {"description": "Return the machine-readable action catalog.", "mutates": False},
    "window": {
        "description": "Export the candidate window from block 1 and write the numbered window.json.",
        "mutates": True,
    },
    "memory": {
        "description": "Read the last fortnight of activated editions and write memory.json.",
        "mutates": True,
    },
    "check-clusters": {
        "description": "Validate the editor's clusters.json and write clusters-checked.json.",
        "mutates": True,
    },
    "score": {"description": "Rank the checked clusters under the policy and write ranking.json.", "mutates": True},
    "build": {"description": "Resolve spec.json into a validated edition.json.", "mutates": True},
    "apply-verdicts": {
        "description": "Strike unsupported sentences and decide which stories still stand.",
        "mutates": True,
    },
    "run": {"description": "Produce one edition end to end under the policy's limits.", "mutates": True},
    "status": {"description": "Report the most recent run.", "mutates": False},
    "deliver": {"description": "Sync block 3's live site to the configured bucket and invalidate the distribution.", "mutates": True},
    "freshness": {"description": "Check the age of the latest activated edition; fail when it is stale.", "mutates": False},
    "preflight": {"description": "Make one cheap request on each login the next run will carry, and on the API key when a login fails.", "mutates": False},
    "verify-live": {
        "description": "Compare the live site with the newsroom's copy; with --fix deliver again when that is the remedy.",
        "mutates": False,
    },
}

Handler = Callable[[argparse.Namespace], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}


def action(name: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS[name] = handler
        return handler

    return register


def _meta() -> dict[str, str]:
    return {"schema_version": SCHEMA_VERSION, "cli_version": __version__}


def _emit(envelope: dict[str, Any]) -> None:
    print(json.dumps(envelope, ensure_ascii=False, default=str, sort_keys=True, separators=(",", ":")))


def _fail(name: str, error_type: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "action": name,
        "error": {"type": error_type, "message": message, "details": details or {}},
        "meta": _meta(),
    }


def build_parser() -> JSONArgumentParser:
    parser = JSONArgumentParser(prog="edit_news.sh", description="The Copenhagen Daily editorial desk.")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list-actions")
    sub.add_parser("status")
    p = sub.add_parser("window")
    p.add_argument("--run", required=True, help="run directory")
    p.add_argument("--cutoff", required=True, help="RFC 3339 UTC cutoff")
    p.add_argument("--bundle", help="use an existing block 1 bundle instead of exporting")
    p.add_argument("--previous-cutoff", help="the previous edition's cutoff; newly observed since it is admitted")
    p.add_argument("--feeds", help="use this coverage inventory instead of block 1's health")
    p = sub.add_parser("memory")
    p.add_argument("--run", required=True)
    p.add_argument("--publish-root", required=True)
    p.add_argument("--registry", help="threads registry; defaults to var/threads.json")
    p = sub.add_parser("check-clusters")
    p.add_argument("--run", required=True)
    p = sub.add_parser("score")
    p.add_argument("--run", required=True)
    p = sub.add_parser("build")
    p.add_argument("--run", required=True)
    p.add_argument("--spec", help="spec path; defaults to <run>/spec.json")
    p.add_argument("--output", help="edition path; defaults to <run>/edition.json")
    p = sub.add_parser("apply-verdicts")
    p.add_argument("--run", required=True)
    p.add_argument("--edition", help="edition to strike; defaults to <run>/edition.json")
    p.add_argument("--verdicts", help="verdicts to apply; defaults to <run>/verdicts.json")
    p.add_argument("--output", help="struck edition; defaults to <run>/edition-checked.json")
    p.add_argument("--final", action="store_true", help="stories that do not stand fall to a headline")
    p = sub.add_parser("run")
    p.add_argument("--cutoff", help="RFC 3339 UTC cutoff; defaults to the policy's cutoff today")
    p.add_argument("--edition", help="edition id; defaults to <date>-<edition>")
    p.add_argument("--publish-root", help="block 3's publish root; defaults to config/desk.yaml")
    p.add_argument("--dry-run", action="store_true", help="build and check, then publish --dry-run; no commit, no memory")
    p.add_argument("--no-collect", action="store_true", help="skip block 1's poll before the export")
    p.add_argument("--checker", choices=["claude", "codex"], help="which tool checks the copy; defaults to config/desk.yaml")
    p.add_argument("--retry", action="store_true", help="run only if today's edition has not already succeeded")
    p = sub.add_parser("deliver")
    p.add_argument("--publish-root", help="block 3's publish root; defaults to config/desk.yaml")
    p = sub.add_parser("freshness")
    p.add_argument("--publish-root", help="block 3's publish root; defaults to config/desk.yaml")
    p.add_argument("--max-age-hours", type=float, help="defaults to config/desk.yaml")
    p.add_argument("--notify", action="store_true", help="send the failure notification when stale")
    p = sub.add_parser("preflight")
    p.add_argument("--checker", choices=["claude", "codex"], help="which tool checks the copy; defaults to config/desk.yaml")
    p.add_argument("--notify", action="store_true", help="send the result, good or bad, through the notifier")
    p = sub.add_parser("verify-live")
    p.add_argument("--publish-root", help="block 3's publish root; defaults to config/desk.yaml")
    p.add_argument("--site-url", help="the live site; defaults to delivery.site_url in config/desk.yaml")
    p.add_argument("--fix", action="store_true", help="deliver again when the site is behind the newsroom's copy")
    p.add_argument("--notify", action="store_true", help="send the verdict, good or bad, through the notifier")
    return parser


def main(argv: list[str] | None = None) -> int:
    from . import actions  # noqa: F401 -- registers handlers

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        _emit(_fail("unknown", "invalid_arguments", str(exc), {"usage": parser.format_usage().strip()}))
        return 2
    name = args.action
    if name is None or name not in ACTIONS:
        _emit(_fail(name or "unknown", "invalid_arguments", "unknown or missing action", {"actions": sorted(ACTIONS)}))
        return 2
    try:
        result = HANDLERS[name](args)
    except ActionError as exc:
        _emit(_fail(name, exc.error_type, str(exc), exc.details))
        return 1
    except Exception as exc:  # noqa: BLE001 -- JSON is the public exception boundary.
        traceback.print_exc(file=sys.stderr)
        _emit(_fail(name, "internal_error", f"{type(exc).__name__}: {exc}"))
        return 1
    _emit({"ok": True, "action": name, "result": result, "meta": _meta()})
    return 0
