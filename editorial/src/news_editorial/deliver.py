"""Delivery: sync block 3's live directory to the bucket and invalidate the distribution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


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
    sync = [aws, "s3", "sync", str(live) + "/", f"s3://{bucket}/", "--delete", "--exact-timestamps", *profile]
    subprocess.run(sync, check=True, capture_output=True, text=True, timeout=900)
    result: dict[str, Any] = {"bucket": bucket, "synced": True}
    if config.get("distribution_id"):
        invalidate = [aws, "cloudfront", "create-invalidation", "--distribution-id", config["distribution_id"], "--paths", "/*", *profile]
        subprocess.run(invalidate, check=True, capture_output=True, text=True, timeout=120)
        result["invalidated"] = config["distribution_id"]
    return result

