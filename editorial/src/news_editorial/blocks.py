"""Call the other blocks' shell wrappers and parse their one-object JSON envelopes."""

from __future__ import annotations

import json
import os
import signal
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


def run_in_group(command: list[str], *, timeout: float, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command in its own process group and, on timeout, take the whole group down.

    `subprocess.run(timeout=...)` kills only the direct child; a wrapper's or a session's
    descendants would go on writing after the runner had recorded a timeout and released its lock."""
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_group(proc)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _end_group(proc: subprocess.Popen[str]) -> None:
    for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def call_wrapper(wrapper: Path, action: str, *args: str, timeout: int = 1800) -> dict[str, Any]:
    command = [str(wrapper), action, *args]
    try:
        proc = run_in_group(command, timeout=timeout)
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
