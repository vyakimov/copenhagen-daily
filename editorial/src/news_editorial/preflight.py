"""The evening check of the logins tomorrow's run will carry: one cheap request on each, and on the
fallback key when the first fails, so a dead token is known the night before, not at 05:30."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from . import blocks
from .paths import INGEST_WRAPPER
from .run import ClaudeAuth, CodexAuth

PROMPT = "Reply with the single word ok."
PROBE_MODEL = "claude-haiku-4-5-20251001"  # only when the desk names no model of its own
TIMEOUT = 120
FEED_FAILURE_ALARM = 20  # consecutive failed polls before a feed is named in the notice


def _probe_claude(command: str, env: dict[str, str] | None, cwd: Path, model: str = PROBE_MODEL) -> dict[str, Any]:
    argv = [command, "-p", PROMPT, "--max-turns", "1", "--output-format", "json", "--strict-mcp-config", "--no-session-persistence", "--model", model]
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


def _probe_codex(command: str, env: dict[str, str] | None, cwd: Path, model: str | None = None) -> dict[str, Any]:
    answer = cwd / "codex-answer.txt"
    argv = [command, "exec", "--skip-git-repo-check", "-s", "read-only", "--ephemeral", "-o", str(answer), "-C", str(cwd)]
    if model:
        argv += ["-m", model]
    argv.append(PROMPT)
    try:
        proc = blocks.run_in_group(argv, cwd=cwd, timeout=TIMEOUT, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"ok": True, "detail": answer.read_text(encoding="utf8").strip()[:80] if answer.is_file() else ""}
    errors = [line for line in proc.stderr.splitlines() if line.startswith("ERROR")]
    detail = (errors[-1] if errors else (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1])
    return {"ok": False, "detail": detail[:300]}


def _probe_claude_models(command: str, env: dict[str, str] | None, cwd: Path, models: list[str]) -> dict[str, Any]:
    """One request per production model, so a retired model is found the night before; the first failure is the finding."""
    for model in models:
        result = _probe_claude(command, env, cwd, model)
        if not result["ok"]:
            return {**result, "model": model, "detail": f"{model}: {result['detail']}"}
    return {**result, "models": models}


def _check_claude(auth: ClaudeAuth, command: str, cwd: Path, models: list[str]) -> dict[str, Any]:
    report: dict[str, Any] = {"primary": {"credential": "token"}, "fallback": None, "usable": None}
    token_env = auth.env() if auth.token() else None
    if token_env is None:
        report["primary"].update(ok=False, detail="no token in editorial/var/claude-oauth.env")
    else:
        report["primary"].update(_probe_claude_models(command, token_env, cwd, models))
    if report["primary"]["ok"]:
        report["usable"] = "token"
        return report
    if not auth.key():
        report["fallback"] = {"credential": "api_key", "ok": False, "detail": "no key in editorial/var/claude-api-key.env"}
        return report
    auth.on_key = True
    report["fallback"] = {"credential": "api_key", **_probe_claude_models(command, auth.env(), cwd, models)}
    if report["fallback"]["ok"]:
        report["usable"] = "api_key"
    return report


def _check_codex(auth: CodexAuth, command: str, cwd: Path, model: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"primary": {"credential": "chatgpt"}, "fallback": None, "usable": None}
    report["primary"].update(_probe_codex(command, None, cwd, model))
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
    report["fallback"] = {"credential": "api_key", **_probe_codex(command, auth.env(), cwd, model)}
    if report["fallback"]["ok"]:
        report["usable"] = "api_key"
    return report


def ingest_health() -> dict[str, Any]:
    """Block 1's health, through its wrapper; its per-feed rows carry `consecutive_failures`."""
    proc = blocks.run_in_group([str(INGEST_WRAPPER), "health"], timeout=600)
    envelope = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}
    return envelope.get("result") or (envelope.get("error") or {}).get("details") or {}


def _check_feeds(health: dict[str, Any]) -> dict[str, Any]:
    """The feeds that have failed more than FEED_FAILURE_ALARM polls running: moved, renamed, or gone."""
    feeds = health.get("feeds") or []
    failing = []
    for feed in feeds:
        count = int(feed.get("consecutive_failures") or 0)
        if count > FEED_FAILURE_ALARM:
            error = feed.get("last_error_json")
            if isinstance(error, str):
                try:
                    error = json.loads(error)
                except json.JSONDecodeError:
                    pass
            message = (error.get("message") or error.get("type") or error.get("error") or str(error)) if isinstance(error, dict) else str(error or "")
            failing.append({"feed_id": feed.get("feed_id"), "consecutive_failures": count, "url": feed.get("url"), "error": str(message)[:120]})
    failing.sort(key=lambda f: (-f["consecutive_failures"], str(f["feed_id"])))
    return {"checked": len(feeds), "failing": failing}


def _check_storage(health: dict[str, Any]) -> dict[str, Any]:
    """Block 1's database size, growth and free disk, and the storage alerts its health raised."""
    alerts = [r for r in health.get("reasons") or [] if r.startswith(("database_growth", "disk_headroom"))]
    return {"database": health.get("database") or {}, "alerts": alerts}


def _storage_line(storage: dict[str, Any]) -> str | None:
    database = storage.get("database") or {}
    if not database:
        return None
    growth = database.get("growth_bytes_per_day")
    change = f"{growth / 2**20:+.0f} MB a day over {database['growth_window_days']:g} days" if growth is not None else "growth not measured yet"
    facts = f"database {database['file_bytes'] / 2**30:.1f} GB, {change}, {database['disk_free_bytes'] / 2**30:.0f} GB free on disk"
    if storage.get("alerts"):
        return f"storage NEEDS ATTENTION ({', '.join(storage['alerts'])}): {facts}. See ingest/docs/operations.md, \"History compaction\"."
    return f"storage: {facts}"


def claude_models(config: dict[str, Any]) -> list[str]:
    """The models tomorrow's Claude sessions will ask for, each once; the cheap probe model when none is configured."""
    models = [m for m in (config.get("editor_model"), config.get("writer_model"), config.get("checker_model") if config.get("checker", "claude") == "claude" else None) if m]
    return list(dict.fromkeys(models)) or [PROBE_MODEL]


def preflight(config: dict[str, Any], *, claude_auth: ClaudeAuth | None = None, codex_auth: CodexAuth | None = None, checker: str | None = None, health: Any = ingest_health) -> dict[str, Any]:
    """Probe each login the next run will use, with the production models, and name the feeds that
    keep failing. `state` is `ready` (every tool on its first choice), `ready_on_fallback` (a tool
    only works on its API key), or `not_ready` (a tool has nothing that works)."""
    claude_auth = claude_auth or ClaudeAuth()
    codex_auth = codex_auth or CodexAuth(codex_command=config.get("codex_command", "codex"))
    checker = checker or config.get("checker", "claude")
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        cwd = Path(tmp)
        tools = {"claude": _check_claude(claude_auth, config.get("editor_command", "claude"), cwd, claude_models(config))}
        if checker == "codex":
            tools["codex"] = _check_codex(codex_auth, config.get("codex_command", "codex"), cwd, config.get("checker_model"))
    if any(t["usable"] is None for t in tools.values()):
        state = "not_ready"
    elif any(t["usable"] == "api_key" for t in tools.values()):
        state = "ready_on_fallback"
    else:
        state = "ready"
    try:
        report = health() if callable(health) else health
        feeds = _check_feeds(report)
        storage = _check_storage(report)
    except Exception as exc:  # noqa: BLE001 -- block 1 being unreachable is itself the finding.
        feeds = {"checked": 0, "failing": [], "error": f"{type(exc).__name__}: {exc}"[:200]}
        storage = {"database": {}, "alerts": []}
    return {"state": state, "checker": checker, **tools, "feeds": feeds, "storage": storage}


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
    feeds = report.get("feeds") or {}
    if feeds.get("error"):
        lines.append(f"feeds: health could not be read ({feeds['error']})")
    elif feeds.get("failing"):
        named = ", ".join(f"{f['feed_id']} ({f['consecutive_failures']} failed polls running: {f['error']})" for f in feeds["failing"])
        lines.append(f"feeds FAILING, {len(feeds['failing'])} of {feeds['checked']}: {named}. Check each feed's URL in ingest/config/sources.yaml.")
    else:
        lines.append(f"feeds: {feeds.get('checked', 0)} checked, none failing")
    storage = report.get("storage") or {}
    if (line := _storage_line(storage)) is not None:
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
    if feeds.get("failing"):
        subject += f"; {len(feeds['failing'])} feeds failing"
    if storage.get("alerts"):
        subject += "; storage needs attention"
    return subject, "\n".join(lines) + "\n" + tail
