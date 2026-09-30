"""Delivery: sync block 3's live directory to the bucket and invalidate the distribution, and push the
device page to the kitchen screen's image host."""

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


def push_device(publish_root: Path, config: dict[str, Any], run: Any = subprocess.run) -> dict[str, Any]:
    """Copy the newest device page to `host:path` with scp. No host configured means the push is skipped.

    Legacy scp (`-O`) because the target is a NAS whose sshd has no SFTP subsystem. The key's
    passphrase comes from the login keychain through ~/.ssh/config, so nothing here holds a secret."""
    host, path = config.get("host"), config.get("path")
    if not host or not path:
        return {"skipped": True, "reason": "no host configured"}
    page = publish_root / "live" / "device" / "current.png"
    if not page.is_file():
        raise RuntimeError(f"{page} does not exist; no device page has been published")
    target = f"{host}:{path}"
    command = ["scp", "-O", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", str(page), target]
    proc = run(command, check=False, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"scp exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()}")
    return {"pushed": True, "to": target, "bytes": page.stat().st_size}
