#!/usr/bin/env python3
"""Compatibility shim; normal fixture captures use gather_news.sh."""

from __future__ import annotations

import argparse

from news_ingest.cli import main


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("feed_id")
    parser.add_argument("destination")
    parser.add_argument("--config", default="config/sources.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cli_args = [
        "capture-fixture",
        "--config",
        args.config,
        "--feed-id",
        args.feed_id,
        "--output",
        args.destination,
    ]
    if args.dry_run:
        cli_args.append("--dry-run")
    return main(cli_args)


if __name__ == "__main__":
    raise SystemExit(_main())
