from __future__ import annotations

import argparse
import asyncio
import json

from . import __version__
from .collect import collect_once
from .config import config_hash, load_config
from .export import export_bundle
from .health import health
from .replay import backup, rebuild_articles, restore_check


def emit(ok, action, result=None, error=None, warnings=None):
    value = {"ok": ok, "action": action, "schema_version": 1}
    if ok:
        value.update(result=result or {}, warnings=warnings or [])
    else:
        value["error"] = {"type": type(error).__name__, "message": str(error), "details": {}}
    print(json.dumps(value, ensure_ascii=False, default=str))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="news-ingest")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate-config", "health"):
        p = sub.add_parser(name)
        p.add_argument("--config", default="config/sources.yaml")
    p = sub.add_parser("collect")
    p.add_argument("--config", default="config/sources.yaml")
    p.add_argument("--source")
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("export")
    p.add_argument("--config", default="config/sources.yaml")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--changed-since")
    p.add_argument("--format", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("backup")
    p.add_argument("--config", default="config/sources.yaml")
    p.add_argument("--output", required=True)
    p = sub.add_parser("restore-check")
    p.add_argument("--backup", required=True)
    p = sub.add_parser("rebuild-articles")
    p.add_argument("--config", default="config/sources.yaml")
    p.add_argument("--source")
    p.add_argument("--dry-run", action="store_true")
    for name in ("replay-payloads", "live-contracts", "enrich", "snapshot-homepages"):
        p = sub.add_parser(name)
        p.add_argument("--config", default="config/sources.yaml")
        p.add_argument("--source")
        p.add_argument("--since")
        p.add_argument("--missing-description", action="store_true")
        p.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "restore-check":
            result = restore_check(args.backup)
        else:
            config = load_config(args.config)
            if args.cmd == "validate-config":
                result = {
                    "config_hash": config_hash(config),
                    "enabled_sources": list(config.enabled_sources()),
                    "enabled_feed_ids": [x[2].id for x in config.enabled_feeds()],
                }
            elif args.cmd == "collect":
                result = asyncio.run(collect_once(config, args.source))
            elif args.cmd == "health":
                result = health(config.database_path, config.failure_alert_threshold)
            elif args.cmd == "export":
                if args.format != "jsonl":
                    raise ValueError("only jsonl is supported")
                result = export_bundle(
                    config.database_path, args.output, args.since, args.until, args.changed_since
                )
            elif args.cmd == "backup":
                backup(config.database_path, args.output)
                result = {"backup": args.output}
            elif args.cmd == "rebuild-articles":
                result = rebuild_articles(config.database_path, args.source, args.dry_run)
            else:
                result = {"status": "disabled", "reason": "disabled in release 1"}
        emit(True, args.cmd, result)
        return 0
    except Exception as exc:  # noqa: BLE001 -- JSON CLI envelope is the public error boundary.
        emit(False, args.cmd, error=exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
