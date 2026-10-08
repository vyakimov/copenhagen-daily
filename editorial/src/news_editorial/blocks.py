"""Call the other blocks' shell wrappers and parse their one-object JSON envelopes."""

from __future__ import annotations

import json
import os
import signal
import time
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


def run_in_group(command: list[str], *, timeout: float, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command in its own process group and, on timeout, take the whole group down.

    `subprocess.run(timeout=...)` kills only the direct child; a wrapper's or a session's
    descendants would go on writing after the runner had recorded a timeout and released its lock.
    Stdin is /dev/null, as under launchd: a session never needs it, and codex waits on an open pipe."""
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_group(proc)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


GRACE_SECONDS = 5.0


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS answers EPERM for a group whose remaining member is exiting; treat it as still there.
        return True
    return True


def _end_group(proc: subprocess.Popen[str]) -> None:
    """Take down the whole process group, not just the direct child. The parent may exit on TERM
    while a descendant that ignores it lives on, so the group is watched until it is empty, and
    SIGKILL follows after the grace period whether or not the parent is still there."""
    pgid = proc.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        deadline = time.monotonic() + GRACE_SECONDS
        while time.monotonic() < deadline:
            proc.poll()  # reap the parent if it has gone, so the group can empty
            if not _group_alive(pgid):
                break
            time.sleep(0.05)
        if not _group_alive(pgid):
            break
    proc.poll()
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


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
