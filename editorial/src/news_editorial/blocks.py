"""Call the other blocks' shell wrappers and parse their one-object JSON envelopes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .paths import INGEST_WRAPPER, PUBLISHER_WRAPPER


class BlockError(Exception):
    def __init__(self, error_type: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


def call_wrapper(wrapper: Path, action: str, *args: str, timeout: int = 1800) -> dict[str, Any]:
    command = [str(wrapper), action, *args]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise BlockError("block_timeout", f"{wrapper.name} {action} exceeded {timeout}s") from exc
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BlockError(
            "block_protocol",
            f"{wrapper.name} {action} did not emit a JSON envelope",
            {"stdout": proc.stdout[-2000:], "exit_code": proc.returncode},
        ) from exc
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        raise BlockError(
            error.get("type", "block_failed"),
            f"{wrapper.name} {action}: {error.get('message', 'failed')}",
            {"upstream": error, "exit_code": proc.returncode},
        )
    return envelope["result"]


def ingest(action: str, *args: str, timeout: int = 1800) -> dict[str, Any]:
    return call_wrapper(INGEST_WRAPPER, action, *args, timeout=timeout)


def publisher(action: str, *args: str, timeout: int = 1800) -> dict[str, Any]:
    return call_wrapper(PUBLISHER_WRAPPER, action, *args, timeout=timeout)
