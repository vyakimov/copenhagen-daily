import json
import shlex
from pathlib import Path

import pytest

from news_editorial.deliver import IMMUTABLE_CACHE, MUTABLE_CACHE, deliver


def fake_aws(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in aws CLI that appends each invocation's arguments, as JSON, to a log."""
    log = tmp_path / "aws-calls.jsonl"
    script = tmp_path / "aws"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\")\" >> {shlex.quote(str(log))}\n")
    script.chmod(0o755)
    return script, log


def calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_delivery_is_skipped_without_a_bucket(tmp_path):
    assert deliver(tmp_path, {})["skipped"] is True


def test_delivery_refuses_a_missing_live_tree(tmp_path):
    with pytest.raises(RuntimeError, match="nothing to deliver"):
        deliver(tmp_path, {"bucket": "b", "aws_command": "false"})


def test_delivery_syncs_immutable_trees_long_and_the_rest_short_then_invalidates(tmp_path):
    (tmp_path / "live").mkdir()
    aws, log = fake_aws(tmp_path)
    result = deliver(tmp_path, {"bucket": "live-bucket", "distribution_id": "E123", "profile": "deliver", "aws_command": str(aws)})
    assert result == {"bucket": "live-bucket", "synced": True, "invalidated": "E123"}
    immutable, mutable, invalidate = calls(log)
    live = str(tmp_path / "live") + "/"
    for sync in (immutable, mutable):
        assert sync[:3] == ["s3", "sync", live] and sync[3] == "s3://live-bucket/"
        assert "--delete" in sync and "--exact-timestamps" in sync and sync[-2:] == ["--profile", "deliver"]
    assert immutable[4:] == ["--delete", "--exact-timestamps", "--exclude", "*", "--include", "n/*", "--include", "a/*",
                             "--cache-control", IMMUTABLE_CACHE, "--profile", "deliver"]
    assert mutable[4:] == ["--delete", "--exact-timestamps", "--exclude", "n/*", "--exclude", "a/*",
                           "--cache-control", MUTABLE_CACHE, "--profile", "deliver"]
    assert "max-age=31536000" in IMMUTABLE_CACHE and "immutable" in IMMUTABLE_CACHE
    assert "max-age=300" in MUTABLE_CACHE
    assert invalidate == ["cloudfront", "create-invalidation", "--distribution-id", "E123", "--paths", "/*", "--profile", "deliver"]
