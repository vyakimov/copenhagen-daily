"""Delivery: sync block 3's live directory to the bucket and invalidate the distribution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# Block 3 publishes two kinds of file. An edition bundle under n/<edition>/ and a layout's assets under
# a/<version>/ never change once published, so a browser may keep them for a year. Everything else at
# the root (index.html, latest.json, index.json, the archive, the feed, the go/ stubs, the device
# image) is rewritten by every publish and must be checked again within minutes, or a reader who
# opened yesterday's paper sees it for hours on the browser's own heuristics.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
MUTABLE_CACHE = "public, max-age=300, must-revalidate"
IMMUTABLE_TREES = ("n/*", "a/*")


def sync_commands(aws: str, live: Path, bucket: str, profile: list[str]) -> list[list[str]]:
    """Two syncs, the immutable trees first so a new front page never names an asset that is not there yet."""
    base = [aws, "s3", "sync", str(live) + "/", f"s3://{bucket}/", "--delete", "--exact-timestamps"]
    immutable = base + ["--exclude", "*"]
    for tree in IMMUTABLE_TREES:
        immutable += ["--include", tree]
    mutable = list(base)
    for tree in IMMUTABLE_TREES:
        mutable += ["--exclude", tree]
    return [
        immutable + ["--cache-control", IMMUTABLE_CACHE, *profile],
        mutable + ["--cache-control", MUTABLE_CACHE, *profile],
    ]


def deliver(publish_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Runs the AWS CLI; a missing bucket in the config means delivery is not set up and is skipped."""
    bucket = config.get("bucket")
    if not bucket:
        return {"skipped": True, "reason": "no bucket configured"}
    aws = config.get("aws_command", "aws")
    profile = ["--profile", config["profile"]] if config.get("profile") else []
    live = publish_root / "live"
    if not live.is_dir():
        raise RuntimeError(f"{live} does not exist; nothing to deliver")
    for sync in sync_commands(aws, live, bucket, profile):
        subprocess.run(sync, check=True, capture_output=True, text=True, timeout=900)
    result: dict[str, Any] = {"bucket": bucket, "synced": True}
    if config.get("distribution_id"):
        invalidate = [aws, "cloudfront", "create-invalidation", "--distribution-id", config["distribution_id"], "--paths", "/*", *profile]
        subprocess.run(invalidate, check=True, capture_output=True, text=True, timeout=120)
        result["invalidated"] = config["distribution_id"]
    return result
