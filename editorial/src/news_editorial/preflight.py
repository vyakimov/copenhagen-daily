"""The evening check of the logins tomorrow's run will carry: one cheap request on each, and on the
fallback key when the first fails, so a dead token is known the night before, not at 05:30."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from . import blocks
from .run import ClaudeAuth, CodexAuth

PROMPT = "Reply with the single word ok."
PROBE_MODEL = "claude-haiku-4-5-20251001"  # the cheapest model; the check is of the login, not the model
TIMEOUT = 120


def _probe_claude(command: str, env: dict[str, str] | None, cwd: Path) -> dict[str, Any]:
    argv = [command, "-p", PROMPT, "--max-turns", "1", "--output-format", "json", "--strict-mcp-config", "--no-session-persistence", "--model", PROBE_MODEL]
    try:
        proc = blocks.run_in_group(argv, cwd=cwd, timeout=TIMEOUT, env=env)
    except Exception as exc:  # noqa: BLE001 -- a probe that cannot run is a failed probe, with the reason.
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        result = {}
    if proc.returncode == 0 and not result.get("is_error"):
        return {"ok": True, "detail": str(result.get("result", "")).strip()[:80], "cost_usd": result.get("total_cost_usd")}
    detail = str(result.get("result") or proc.stderr.strip().splitlines()[-1:] or f"exit {proc.returncode}")
    return {"ok": False, "detail": detail[:300]}


def _probe_codex(command: str, env: dict[str, str] | None, cwd: Path) -> dict[str, Any]:
    answer = cwd / "codex-answer.txt"
    argv = [command, "exec", "--skip-git-repo-check", "-s", "read-only", "--ephemeral", "-o", str(answer), "-C", str(cwd), PROMPT]
    try:
        proc = blocks.run_in_group(argv, cwd=cwd, timeout=TIMEOUT, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"ok": True, "detail": answer.read_text(encoding="utf8").strip()[:80] if answer.is_file() else ""}
    errors = [line for line in proc.stderr.splitlines() if line.startswith("ERROR")]
    detail = (errors[-1] if errors else (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1])
    return {"ok": False, "detail": detail[:300]}


def _check_claude(auth: ClaudeAuth, command: str, cwd: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"primary": {"credential": "token"}, "fallback": None, "usable": None}
    token_env = auth.env() if auth.token() else None
    if token_env is None:
        report["primary"].update(ok=False, detail="no token in editorial/var/claude-oauth.env")
    else:
        report["primary"].update(_probe_claude(command, token_env, cwd))
    if report["primary"]["ok"]:
        report["usable"] = "token"
        return report
    if not auth.key():
        report["fallback"] = {"credential": "api_key", "ok": False, "detail": "no key in editorial/var/claude-api-key.env"}
        return report
    auth.on_key = True
    report["fallback"] = {"credential": "api_key", **_probe_claude(command, auth.env(), cwd)}
    if report["fallback"]["ok"]:
        report["usable"] = "api_key"
    return report


def _check_codex(auth: CodexAuth, command: str, cwd: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"primary": {"credential": "chatgpt"}, "fallback": None, "usable": None}
    report["primary"].update(_probe_codex(command, None, cwd))
    if report["primary"]["ok"]:
        report["usable"] = "chatgpt"
        return report
    key = auth.key()
    if not key:
        report["fallback"] = {"credential": "api_key", "ok": False, "detail": "no key in editorial/var/codex-api-key.env"}
        return report
    try:
        auth.log_in(key)
    except Exception as exc:  # noqa: BLE001 -- `codex login` failing is the finding.
        report["fallback"] = {"credential": "api_key", "ok": False, "detail": f"codex login --with-api-key failed: {exc}"[:300]}
        return report
    auth.on_key = True
    report["fallback"] = {"credential": "api_key", **_probe_codex(command, auth.env(), cwd)}
    if report["fallback"]["ok"]:
        report["usable"] = "api_key"
    return report


def preflight(config: dict[str, Any], *, claude_auth: ClaudeAuth | None = None, codex_auth: CodexAuth | None = None, checker: str | None = None) -> dict[str, Any]:
    """Probe each login the next run will use. `state` is `ready` (every tool on its first choice),
    `ready_on_fallback` (a tool only works on its API key), or `not_ready` (a tool has nothing that works)."""
    claude_auth = claude_auth or ClaudeAuth()
    codex_auth = codex_auth or CodexAuth(codex_command=config.get("codex_command", "codex"))
    checker = checker or config.get("checker", "claude")
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        cwd = Path(tmp)
        tools = {"claude": _check_claude(claude_auth, config.get("editor_command", "claude"), cwd)}
        if checker == "codex":
            tools["codex"] = _check_codex(codex_auth, config.get("codex_command", "codex"), cwd)
    if any(t["usable"] is None for t in tools.values()):
        state = "not_ready"
    elif any(t["usable"] == "api_key" for t in tools.values()):
        state = "ready_on_fallback"
    else:
        state = "ready"
    return {"state": state, "checker": checker, **tools}


def summary(report: dict[str, Any]) -> tuple[str, str]:
    """The notification: one line per tool, the subject for the state."""
    names = {"token": "token", "chatgpt": "ChatGPT login", "api_key": "API key"}
    lines = []
    for tool in ("claude", "codex"):
        if tool not in report:
            continue
        t = report[tool]
        primary = t["primary"]
        line = f"{tool}: {names[primary['credential']]} {'ok' if primary['ok'] else 'FAILED (' + primary['detail'] + ')'}"
        if t["fallback"] is not None:
            fb = t["fallback"]
            line += f"; API key {'ok' if fb['ok'] else 'FAILED (' + fb['detail'] + ')'}"
        lines.append(line)
    if report["state"] == "ready":
        subject = "Copenhagen Daily: tomorrow's logins are ready"
        tail = "Every session runs on its first choice."
    elif report["state"] == "ready_on_fallback":
        subject = "Copenhagen Daily: tomorrow's run will use an API key"
        tail = "The run will go ahead on the key, billed. Renew the failed login before 05:30 to avoid that (editorial/OPERATIONS.md, \"The desk's own login\")."
    else:
        subject = "Copenhagen Daily: tomorrow's run CANNOT log in"
        tail = "Without a working login the 05:30 run fails at the desk. Renew the login or add a key tonight (editorial/OPERATIONS.md, \"The desk's own login\")."
    return subject, "\n".join(lines) + "\n" + tail
