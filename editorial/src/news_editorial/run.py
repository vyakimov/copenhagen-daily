"""The runner: one edition end to end, deterministic steps around bounded sessions.

The desk session clusters, selects and keeps the log; one small read-only session per story writes
the copy from that story's evidence alone; the checker marks every sentence. The runner assembles the
spec, builds the contract, and never lets a session see more than its job needs.

The output is the web edition, and, when the desk config asks, block 3's page for the kitchen screen,
fitted from the same contract; the contract's device fields are filled mechanically by `build`.

Every phase ends in a file in the run directory and a line in status.json. Nothing retries a model
step blindly; a failure keeps the last activated edition in place and says why.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import fcntl
import re
import threading
import hashlib
import json
import os
import subprocess
import traceback
import sys
import time
import zoneinfo
from pathlib import Path
from typing import Any, Callable

import yaml

from . import blocks
from .blocks import BlockError
from .build import BuildError, build_edition, spec_story, validate_story_copy, write_edition
from .bundle import BundleError, load_bundle
from .clusters import check_clusters, write_checked  # noqa: F401 -- re-exported for the desk
from .contract import validate_edition
from .deliver import deliver
from .lookups import wikipedia_summary
from .notify import notify
from .memory import build_memory, load_registry, save_registry, write_memory
from .paths import EDITORIAL, REPO, RUNS, VAR
from .policy import Policy
from .verdicts import apply_verdicts, check_input, coverage_problems, strict_verdicts_schema, validate_verdicts, without_nulls
from .window import build_window, write_window

DESK_CONFIG = EDITORIAL / "config" / "desk.yaml"
LOCK_PATH = VAR / "run.lock"
# The desk actions an editor session may call. `run` is deliberately absent: a session must never
# start another run, publish, or reach block 1 or block 3 through the wrapper.
EDITOR_ACTIONS = ("check-clusters", "score")
# The golden edition: one story of each role goes into a writer's brief as the voice to match.
GOLDEN_SPEC = EDITORIAL / "examples" / "2026-09-15-morning" / "spec.json"
WRITER_SKILL = REPO / "skills" / "story-writer" / "SKILL.md"
# What the archive commits: the desk's own work. The check input and the verdicts stay out of git
# because they quote the publishers' text; they remain in the run directory on disk.
SMALL_FILES = [
    "feeds.json", "memory.json", "clusters.json", "clusters-checked.json", "ranking.json", "selection.json", "spec.json",
    "edition.json", "send-back.json", "edition-checked.json",
    "NOTES.md", "status.json", "stories",
]


class RunFailure(Exception):
    def __init__(self, error_type: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


DESK_LOCAL_CONFIG = VAR / "desk.local.yaml"


def load_desk_config(path: Path = DESK_CONFIG, local: Path = DESK_LOCAL_CONFIG) -> dict[str, Any]:
    """config/desk.yaml, with var/desk.local.yaml laid over it one level deep. The committed file
    holds the shape and the defaults; the local file, which git ignores, holds this deployment's
    names: the bucket, the distribution, the CLI profile, the kitchen screen's host and path."""
    with path.open(encoding="utf8") as handle:
        config = yaml.safe_load(handle) or {}
    if local.is_file():
        with local.open(encoding="utf8") as handle:
            overlay = yaml.safe_load(handle) or {}
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key] = {**config[key], **value}
            else:
                config[key] = value
    return config


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def cutoff_for(date: str, policy: Policy) -> str:
    """The policy's local cutoff on a date, as the contract's UTC timestamp."""
    hour, minute = (int(x) for x in policy.schedule.cutoff_local.split(":"))
    tz = zoneinfo.ZoneInfo(policy.timezone)
    local = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(hour, minute), tzinfo=tz)
    return local.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def edition_date_for(cutoff: str, policy: Policy) -> str:
    when = dt.datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(zoneinfo.ZoneInfo(policy.timezone))
    return when.date().isoformat()


# ---------------------------------------------------------------------------------------------------
# The sessions


def _session_record(run_dir: Path, name: str, record: dict[str, Any]) -> None:
    sessions = run_dir / "sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf8")


OAUTH_TOKEN_PATH = VAR / "claude-oauth.env"
API_KEY_PATH = VAR / "claude-api-key.env"
AUTH_FALLBACK_RECORD = "auth-fallback.json"


def read_secret(path: Path, key: str) -> str | None:
    """A secret kept in var: the bare value on its own line, or `KEY=value`. None without the file or a value."""
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            line = value.strip().strip('"').strip("'")
        return line or None
    return None


def claude_oauth_token(path: Path | None = None) -> str | None:
    """The long-lived token from `claude setup-token`, kept in var/claude-oauth.env."""
    return read_secret(OAUTH_TOKEN_PATH if path is None else path, "CLAUDE_CODE_OAUTH_TOKEN")




class ClaudeAuth:
    """Which credential the Claude sessions of one run carry.

    The token from var/claude-oauth.env comes first. The API key from var/claude-api-key.env is the
    fallback, used only when there is no token or a session failed to authenticate with it, and from
    then on for the rest of the run: one invalid token is invalid for every session. A new run starts
    over with the token. The owner is told the first time a run moves to the key, since the key is
    billed and the token needs renewing. The codex checker never sees either credential."""

    def __init__(self, token_path: Path | None = None, key_path: Path | None = None, notifier: Callable[[str, str], Any] | None = None, edition_id: str = ""):
        self.token_path = token_path
        self.key_path = key_path
        self.notifier = notifier
        self.edition_id = edition_id
        self.on_key = False

    def token(self) -> str | None:
        return read_secret(OAUTH_TOKEN_PATH if self.token_path is None else self.token_path, "CLAUDE_CODE_OAUTH_TOKEN")

    def key(self) -> str | None:
        return read_secret(API_KEY_PATH if self.key_path is None else self.key_path, "ANTHROPIC_API_KEY")

    @staticmethod
    def rejected(record: dict[str, Any]) -> bool:
        """Whether a session's record says the credential, not the work, failed."""
        result = str(record.get("result") or "")
        return bool(record.get("is_error")) and ("Failed to authenticate" in result or "authentication_error" in result)

    def env(self, run_dir: Path | None = None, session: str = "") -> dict[str, str] | None:
        """The session's environment: the runner's plus one credential, or None to inherit as is."""
        base = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
        if not self.on_key:
            token = self.token()
            if token:
                return {**base, "CLAUDE_CODE_OAUTH_TOKEN": token}
            if self.fall_back("token_missing", run_dir, session):
                return {**base, "ANTHROPIC_API_KEY": str(self.key())}
            return None
        key = self.key()
        return {**base, "ANTHROPIC_API_KEY": key} if key else None

    def fall_back(self, reason: str, run_dir: Path | None, session: str) -> bool:
        """Move the run to the API key if there is one; tell the owner the first time. False without a key."""
        key = self.key()
        if not key:
            return False
        if self.on_key:
            return True
        self.on_key = True
        if run_dir is not None:
            _session_record(run_dir, AUTH_FALLBACK_RECORD.removesuffix(".json"), {"reason": reason, "session": session, "at": _now()})
        self._tell(reason)
        return True

    def _tell(self, reason: str) -> None:
        if not self.notifier:
            return
        edition = self.edition_id or "today's edition"
        subject = f"Copenhagen Daily: {edition} is running on the API key"
        why = "there is no token in editorial/var/claude-oauth.env" if reason == "token_missing" else "a session failed to authenticate with the token in editorial/var/claude-oauth.env"
        body = (
            f"The Claude sessions of {edition} are using the API key from editorial/var/claude-api-key.env because {why}. "
            "The run goes on, billed to the key. Mint a new token at the keyboard with `claude setup-token > editorial/var/claude-oauth.env` "
            "so the next run is back on the subscription; every run tries the token first."
        )
        try:
            self.notifier(subject, body)
        except Exception as exc:  # noqa: BLE001 -- a failed notification must not stop the paper; the record in the run directory remains.
            sys.stderr.write(f"notification failed: {exc}\nNOTIFY {subject}\n{body}\n")


AUTH = ClaudeAuth()

CODEX_KEY_PATH = VAR / "codex-api-key.env"
CODEX_KEY_HOME = VAR / "codex-api-home"
CODEX_REJECTIONS = ("401 Unauthorized", "Missing bearer", "403 Forbidden", "Quota exceeded", "usage limit", "not logged in", "Not logged in")


class CodexAuth:
    """Which login the codex checker runs under.

    Codex reads its login from `$CODEX_HOME/auth.json` (by default `~/.codex`), the owner's ChatGPT
    login, and ignores an API key in the environment. The fallback is a second codex home in var,
    logged in once with the key from var/codex-api-key.env through `codex login --with-api-key` and
    carrying a copy of the owner's config.toml so the model settings are the same. A checker that
    fails on its login or its quota is run once more in that home, and the run stays there; the next
    run starts over with the ChatGPT login. The owner is told the first time, since the key is billed."""

    def __init__(self, key_path: Path | None = None, key_home: Path | None = None, notifier: Callable[[str, str], Any] | None = None, edition_id: str = "", codex_command: str = "codex"):
        self.key_path = CODEX_KEY_PATH if key_path is None else key_path
        self.key_home = CODEX_KEY_HOME if key_home is None else key_home
        self.notifier = notifier
        self.edition_id = edition_id
        self.codex_command = codex_command
        self.on_key = False

    def key(self) -> str | None:
        return read_secret(self.key_path, "OPENAI_API_KEY")

    @staticmethod
    def rejected(record: dict[str, Any]) -> bool:
        text = str(record.get("stderr_tail") or "") + str(record.get("stdout") or "")
        return record.get("exit_code") != 0 and any(mark in text for mark in CODEX_REJECTIONS)

    def env(self, run_dir: Path | None = None, session: str = "") -> dict[str, str] | None:
        if not self.on_key:
            return None
        return {**os.environ, "CODEX_HOME": str(self.key_home)}

    def fall_back(self, reason: str, run_dir: Path | None, session: str) -> bool:
        key = self.key()
        if not key:
            return False
        if self.on_key:
            return True
        self._log_in(key)
        self.on_key = True
        if run_dir is not None:
            _session_record(run_dir, "auth-fallback-codex", {"reason": reason, "session": session, "at": _now()})
        self._tell()
        return True

    def _log_in(self, key: str) -> None:
        """Log the key into its own codex home, fresh each time, with the owner's config beside it."""
        self.key_home.mkdir(parents=True, exist_ok=True)
        (self.key_home / "auth.json").unlink(missing_ok=True)
        subprocess.run(
            [self.codex_command, "login", "--with-api-key"], input=key, text=True, check=True, capture_output=True, timeout=60,
            env={**os.environ, "CODEX_HOME": str(self.key_home)},
        )
        owner_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        config = owner_home / "config.toml"
        if config.is_file():
            (self.key_home / "config.toml").write_text(config.read_text(encoding="utf8"), encoding="utf8")

    def _tell(self) -> None:
        if not self.notifier:
            return
        edition = self.edition_id or "today's edition"
        subject = f"Copenhagen Daily: the codex checker of {edition} is running on the API key"
        body = (
            f"The codex checker of {edition} could not run on the ChatGPT login, so it is running on the API key from "
            "editorial/var/codex-api-key.env, in its own codex home under editorial/var. The run goes on, billed to the key. "
            "Run `codex login` at the keyboard to restore the ChatGPT login; every run tries it first."
        )
        try:
            self.notifier(subject, body)
        except Exception as exc:  # noqa: BLE001 -- a failed notification must not stop the paper; the record in the run directory remains.
            sys.stderr.write(f"notification failed: {exc}\nNOTIFY {subject}\n{body}\n")


CODEX_AUTH = CodexAuth()


def _headless(command: list[str], cwd: Path, timeout: int, name: str, run_dir: Path, limit: str, auth: ClaudeAuth | CodexAuth | None = None) -> dict[str, Any]:
    """Run a session once; a session whose credential was rejected is run once more on the API key
    when `auth` can fall back, and both attempts are on record."""
    env = auth.env(run_dir, name) if auth is not None else None
    record = _headless_once(command, cwd, timeout, name, run_dir, limit, env)
    if auth is not None and auth.rejected(record) and not auth.on_key:
        reason = "login_rejected" if isinstance(auth, CodexAuth) else "token_rejected"
        if auth.fall_back(reason, run_dir, name):
            record = _headless_once(command, cwd, timeout, f"{name}-api-key", run_dir, limit, auth.env(run_dir, name))
    if record["exit_code"] != 0 or record.get("is_error"):
        raise RunFailure(f"{name.split('-')[0]}_failed", f"{name} exited {record['exit_code']}", {"record": record})
    if auth is not None:
        record["auth"] = "api_key" if auth.on_key else ("chatgpt" if isinstance(auth, CodexAuth) else "token")
    return record


def _headless_once(command: list[str], cwd: Path, timeout: int, name: str, run_dir: Path, limit: str, env: dict[str, str] | None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = blocks.run_in_group(command, cwd=cwd, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        _session_record(run_dir, name, {"command": command[:2], "timed_out_after_s": timeout})
        raise RunFailure(f"{limit}_timeout", f"{name} ran past its wall clock of {timeout}s", {"limit": limit}) from exc
    elapsed = round(time.monotonic() - started, 1)
    if proc.stderr:
        sys.stderr.write(proc.stderr[-4000:])
    record: dict[str, Any] = {"command": command[:2], "exit_code": proc.returncode, "elapsed_s": elapsed}
    if proc.returncode != 0 and proc.stderr:
        record["stderr_tail"] = proc.stderr[-1500:]
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"stdout": proc.stdout[-4000:]}
    except json.JSONDecodeError:
        result = {"stdout": proc.stdout[-4000:]}
    for key in ("session_id", "num_turns", "duration_ms", "total_cost_usd", "is_error", "subtype", "permission_denials", "result"):
        if key in result:
            record[key] = result[key]
    _session_record(run_dir, name, record)
    return record


def invoke_editor(mode: str, run_dir: Path, timeout: int, config: dict[str, Any] | None = None, max_turns: int | None = None, auth: ClaudeAuth | None = None) -> dict[str, Any]:
    config = config or load_desk_config()
    wrapper = EDITORIAL / "edit_news.sh"
    prompt = (
        f"Read {REPO / 'skills' / 'editorial-desk' / 'SKILL.md'} and follow it exactly. "
        f"Run directory: {run_dir}. Edition id: {run_dir.name}. Mode: {mode}."
    )
    command = [
        config.get("editor_command", "claude"), "-p", prompt,
        "--output-format", "json", "--permission-mode", "acceptEdits", "--add-dir", str(REPO),
        "--allowedTools", ",".join(f"Bash({wrapper} {action} *)" for action in EDITOR_ACTIONS),
        "--disallowedTools", "WebFetch,WebSearch",
        "--strict-mcp-config", "--no-session-persistence",
    ]
    if max_turns:
        command += ["--max-turns", str(max_turns)]
    if config.get("editor_model"):
        command += ["--model", config["editor_model"]]
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"editor-{mode}-{_now()[:19]}", run_dir=run_dir, limit="editor", auth=AUTH if auth is None else auth)


def invoke_writer(brief: Path, timeout: int, config: dict[str, Any] | None = None, max_turns: int | None = None, auth: ClaudeAuth | None = None) -> dict[str, Any]:
    """One story's writing session: it may read, and only read, and its final message is the copy.

    Its working directory is the story's own, holding the brief and nothing else, and no other
    directory is added, so a headless session is denied any read outside it: the whole window, the
    other stories' briefs and the desk's files are out of reach, not merely out of the prompt. The
    skill text, the style guide and the guidelines travel inside the brief for the same reason."""
    config = config or load_desk_config()
    run_dir = brief.parents[2]
    prompt = (
        f"Read {brief.name} in your working directory and follow its `skill` text exactly. "
        "Your final message is the story JSON and nothing else."
    )
    command = [
        config.get("editor_command", "claude"), "-p", prompt,
        "--output-format", "json", "--tools", "Read",
        "--disallowedTools", "Bash,Write,Edit,MultiEdit,NotebookEdit,WebFetch,WebSearch,Agent,Task",
        "--strict-mcp-config", "--no-session-persistence",
    ]
    if max_turns:
        command += ["--max-turns", str(max_turns)]
    model = config.get("writer_model") or config.get("editor_model")
    if model:
        command += ["--model", model]
    return _headless(command, cwd=brief.parent, timeout=timeout, name=f"writer-{brief.parent.name}-{_now()[:19]}", run_dir=run_dir, limit="writer", auth=AUTH if auth is None else auth)


def invoke_checker(run_dir: Path, timeout: int, config: dict[str, Any] | None = None, max_turns: int | None = None, auth: ClaudeAuth | None = None, codex_auth: CodexAuth | None = None) -> dict[str, Any]:
    config = config or load_desk_config()
    tool = config.get("checker", "claude")
    session_auth: ClaudeAuth | CodexAuth | None = None
    if tool == "codex":
        session_auth = CODEX_AUTH if codex_auth is None else codex_auth
        session_auth.codex_command = config.get("codex_command", "codex")
        prompt = (
            f"Read {EDITORIAL / 'VERIFIER.md'} and follow it exactly. Read {run_dir / 'check-input.json'}. "
            "Your final message is the verdicts JSON and nothing else."
        )
        schema_path = run_dir / "sessions" / "verdicts.strict.schema.json"
        schema_path.parent.mkdir(exist_ok=True)
        schema_path.write_text(json.dumps(strict_verdicts_schema(), indent=1) + "\n", encoding="utf8")
        command = [
            config.get("codex_command", "codex"), "exec", "--skip-git-repo-check", "-s", "read-only", "--ephemeral",
            "--output-schema", str(schema_path), "-o", str(run_dir / "verdicts.json"), "-C", str(run_dir),
        ]
        if config.get("checker_model"):
            command += ["-m", config["checker_model"]]
        command.append(prompt)
    else:
        prompt = f"Read {REPO / 'skills' / 'editorial-checker' / 'SKILL.md'} and follow it exactly. Run directory: {run_dir}."
        command = [
            config.get("editor_command", "claude"), "-p", prompt,
            "--output-format", "json", "--permission-mode", "acceptEdits", "--add-dir", str(REPO),
            "--disallowedTools", "WebFetch,WebSearch,Bash",
            "--strict-mcp-config", "--no-session-persistence",
        ]
        if max_turns:
            command += ["--max-turns", str(max_turns)]
        if config.get("checker_model"):
            command += ["--model", config["checker_model"]]
        session_auth = AUTH if auth is None else auth
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"checker-{_now()[:19]}", run_dir=run_dir, limit="checker", auth=session_auth)


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True)


def _stray_changes(repo: Path = REPO) -> list[str]:
    """Paths the working tree has changed, relative to the repository root, as git reports them."""
    proc = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, check=True, capture_output=True, text=True)
    return [line[3:].split(" -> ")[-1] for line in proc.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------------------------------
# The runner


class Runner:
    def __init__(
        self,
        policy: Policy,
        run_dir: Path,
        edition_id: str,
        cutoff: str,
        publish_root: Path,
        registry: Path,
        *,
        ingest: Callable[..., dict[str, Any]] = blocks.ingest,
        publisher: Callable[..., dict[str, Any]] = blocks.publisher,
        editor: Callable[[str, Path, int], dict[str, Any]] = invoke_editor,
        writer: Callable[[Path, int], dict[str, Any]] = invoke_writer,
        checker: Callable[[Path, int], dict[str, Any]] = invoke_checker,
        lookup: Callable[[str], dict[str, Any]] = wikipedia_summary,
        git: Callable[..., None] = _git,
        stray_changes: Callable[[], list[str]] = _stray_changes,
        lock_path: Path = LOCK_PATH,
        collect: bool = True,
        dry_run: bool = False,
        commit: bool = True,
        repo: Path = REPO,
        notifier: Callable[[str, str], Any] | None = None,
        deliverer: Callable[[Path], dict[str, Any]] | None = None,
        device: bool = False,
        retry: bool = False,
        collect_wait_seconds: int = 30,
        collect_max_attempts: int = 20,
        collect_max_age_minutes: int = 20,
        now: Callable[[], str] = _now,
    ):
        self.collect_wait_seconds = collect_wait_seconds
        self.collect_max_attempts = collect_max_attempts
        self.collect_max_age_minutes = collect_max_age_minutes
        self.now = now
        self.repo = repo
        self.notifier = notifier
        self.deliverer = deliverer
        self.device = device
        self.retry = retry
        self.activated_before = False
        self.stray_changes = stray_changes
        self.lock_path = lock_path
        self.policy = policy
        self.run_dir = run_dir
        self.edition_id = edition_id
        self.cutoff = cutoff
        self.publish_root = publish_root
        self.registry = registry
        self.ingest = ingest
        self.publisher = publisher
        self.editor = editor
        self.writer = writer
        self.lookup = lookup
        self._inputs_lock = threading.Lock()
        self.checker = checker
        self.git = git
        self.collect = collect
        self.dry_run = dry_run
        self.commit = commit
        self.started = time.monotonic()
        self.status: dict[str, Any] = {
            "schema_version": 1,
            "edition_id": edition_id,
            "cutoff_at": cutoff,
            "started_at": _now(),
            "dry_run": dry_run,
            "outcome": "running",
            "phases": [],
            "failure": None,
            "published": None,
        }

    # -- bookkeeping ---------------------------------------------------------------------------------

    def _write_status(self) -> None:
        self.status["updated_at"] = _now()
        self.status["elapsed_s"] = round(time.monotonic() - self.started, 1)
        (self.run_dir / "status.json").write_text(json.dumps(self.status, ensure_ascii=False, indent=1) + "\n", encoding="utf8")

    def _phase(self, name: str, **fields: Any) -> dict[str, Any]:
        record = {"name": name, "finished_at": _now(), **fields}
        self.status["phases"].append(record)
        self._write_status()
        return record

    def _remaining(self) -> int:
        return int(self.policy.limits.run_minutes * 60 - (time.monotonic() - self.started))

    def _budget(self, minutes: int) -> int:
        seconds = min(minutes * 60, self._remaining())
        if seconds <= 0:
            raise RunFailure("run_timeout", "the run has used its wall clock", {"limit": "run_minutes"})
        return seconds

    def _read(self, name: str) -> Any:
        path = self.run_dir / name
        if not path.is_file():
            raise RunFailure("phase_output_missing", f"{name} was not written", {"path": str(path)})
        return json.loads(path.read_text(encoding="utf8"))

    def _write(self, name: str, doc: Any) -> Path:
        path = self.run_dir / name
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
        return path

    # -- phases --------------------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        if (self.run_dir / "status.json").is_file():
            previous = json.loads((self.run_dir / "status.json").read_text(encoding="utf8"))
            if self.retry and previous.get("outcome") in {"published", "dry_run", "skipped"}:
                self.status = previous
                self.status["outcome"] = "skipped"
                self.status["skipped_reason"] = f"the edition already ended as {previous.get('outcome')}"
                return self.status
            if previous.get("outcome") == "published":
                raise RunFailure("conflict", f"{self.edition_id} is already published; an edition id is used once", {"run": str(self.run_dir)})
            # The history of what went wrong before is kept with the run, not overwritten by the retry.
            if previous.get("failure"):
                self.status["previous_failures"] = [*previous.get("previous_failures", []), {**previous["failure"], "at": previous.get("updated_at")}]
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.status["outcome"] = "failed"
                self.status["failure"] = {"phase": "start", "type": "lock_busy", "message": f"another run holds {self.lock_path}", "details": {"lock": str(self.lock_path)}}
                return self.status
            lock.seek(0)
            lock.truncate()
            lock.write(f"{self.edition_id} {_now()}\n")
            lock.flush()
            return self._run_locked()

    def _run_locked(self) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_status()
        phase = "start"
        try:
            for phase, step in (
                ("reconcile", self._reconcile),
                ("inputs", self._verify_inputs),
                ("collect", self._collect),
                ("window", self._window),
                ("memory", self._memory),
                ("editor", self._editor),
                ("write", self._write_copy),
                ("check", self._check),
                ("preflight", self._preflight),
                ("publish", self._publish),
                ("receipt", self._receipt),
                ("threads", self._threads),
                ("deliver", self._deliver),
                ("archive", self._archive),
            ):
                if self.activated_before and phase in self.BEFORE_ACTIVATION:
                    self._phase(phase, skipped=True, reason="already_activated")
                    continue
                step()
        except (RunFailure, BlockError) as exc:
            self.status["outcome"] = "failed"
            self.status["failure"] = {"phase": phase, "type": exc.error_type, "message": str(exc), "details": exc.details}
            self._write_status()
            self._notify_failure()
            return self.status
        except Exception as exc:  # noqa: BLE001 -- a run that dies must not leave status.json at "running".
            self.status["outcome"] = "failed"
            self.status["failure"] = {"phase": phase, "type": "internal_error", "message": f"{type(exc).__name__}: {exc}", "details": {"traceback": traceback.format_exc()[-4000:]}}
            self._write_status()
            self._notify_failure()
            return self.status
        if self.status["outcome"] == "running":
            self.status["outcome"] = "dry_run" if self.dry_run else "published"
            self._write_status()
        return self.status

    BEFORE_ACTIVATION = ("inputs", "collect", "window", "memory", "editor", "write", "check", "preflight", "publish")

    def _reconcile(self) -> None:
        """Ask block 3 whether this edition is already activated. If it is, a previous run got as far
        as publishing and failed after; the phases up to the publish are settled and only the ones
        after it run again, each of them idempotent. Publishing twice is impossible anyway: block 3
        refuses a stored edition, so without this step a retry could never finish the delivery."""
        self.activated_before = False
        if self.dry_run:
            self._phase("reconcile", skipped=True)
            return
        try:
            result = self.publisher("receipt", "--publish-root", str(self.publish_root), "--edition", self.edition_id, timeout=self._budget(2))
        except BlockError as exc:
            if exc.error_type in {"resource_not_found", "edition_not_activated"}:
                self._phase("reconcile", activated=False)
                return
            if exc.error_type == "recovery_required":
                raise RunFailure("recovery_required", "block 3 holds a pending publication; run publish_news.sh recover, then retry", {"upstream": exc.details}) from exc
            raise
        if not result.get("activated"):
            self._phase("reconcile", activated=False)
            return
        self.activated_before = True
        self.status["published"] = {
            "edition": str(self.run_dir / "edition-checked.json"),
            "status": "published",
            "device_status": (result.get("receipt") or {}).get("device", {}).get("status"),
            "bundle": {"path": f"n/{self.edition_id}/", "manifest_sha256": result.get("manifest_sha256")},
            "resumed": True,
        }
        self._phase("reconcile", activated=True, sequence=result.get("activation", {}).get("sequence"))

    def _collect(self) -> None:
        """Poll once more so the window is current. The scheduled collector may hold block 1's lock;
        wait for it, and if it never frees, go on with its poll, which is at most an interval old."""
        if not self.collect:
            self._phase("collect", skipped=True)
            return
        # The scheduled collector polls every few minutes; when its last poll is recent enough, a
        # second poll buys nothing and only competes for the lock.
        health = self.ingest("health", timeout=self._budget(2))
        # Every feed that is not known to be failing must have polled recently; one fresh feed says
        # nothing about the rest after an interrupted or partial collection.
        healthy = [f for f in health.get("feeds", []) if not f.get("consecutive_failures")]
        polls = [f.get("last_successful_poll_at") or "" for f in healthy]
        last = min(polls, default="") if polls and all(polls) else ""
        if last:
            age = dt.datetime.fromisoformat(self.now().replace("Z", "+00:00")) - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))
            if age <= dt.timedelta(minutes=self.collect_max_age_minutes):
                self._phase("collect", skipped=True, reason="recent_poll", last_poll_at=last, age_minutes=round(age.total_seconds() / 60, 1))
                return
        waited = 0
        while True:
            try:
                result = self.ingest("collect", "--once", timeout=self._budget(15))
                self._phase("collect", status=result.get("status"), waited_attempts=waited)
                return
            except BlockError as exc:
                if exc.error_type != "lock_busy":
                    raise
                waited += 1
                if waited >= self.collect_max_attempts:
                    self._phase("collect", skipped=True, reason="lock_busy", waited_attempts=waited)
                    return
                time.sleep(self.collect_wait_seconds)

    def _window(self) -> None:
        if (self.run_dir / "window.json").is_file():
            self._phase("window", resumed=True)
            return
        cutoff = dt.datetime.fromisoformat(self.cutoff.replace("Z", "+00:00"))
        since = cutoff - dt.timedelta(hours=self.policy.schedule.candidate_window_hours)
        bundle_path = self.run_dir / "bundle"
        if not bundle_path.exists():
            self.ingest("export", "--since", since.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "--until", self.cutoff, "--output", str(bundle_path), timeout=self._budget(10))
        try:
            bundle = load_bundle(bundle_path)
        except BundleError as exc:
            raise RunFailure("bundle_invalid", str(exc)) from exc
        health = self.ingest("health", timeout=self._budget(2))
        feeds = []
        for feed in health["feeds"]:
            outcome = "not_checked" if feed["last_checked_at"] is None else ("failed" if feed.get("consecutive_failures") else "checked")
            feeds.append({"feed_id": feed["feed_id"], "source": feed["source"], "outcome": outcome, "last_checked_at": feed["last_checked_at"]})
        feeds.sort(key=lambda f: f["feed_id"])
        self._write("feeds.json", feeds)
        previous = self._previous_cutoff()
        window = build_window(bundle, self.policy, cutoff=self.cutoff, previous_cutoff=previous)
        write_window(window, self.run_dir)
        self._record_inputs()
        self._phase("window", articles=len(window["articles"]), feeds=len(feeds), failed_feeds=sum(1 for f in feeds if f["outcome"] != "checked"))

    def _previous_cutoff(self) -> str | None:
        memory = build_memory(self.publish_root, self.registry, self.policy, cutoff=self.cutoff)
        return memory["previous_cutoff_at"]

    def _memory(self) -> None:
        memory = build_memory(self.publish_root, self.registry, self.policy, cutoff=self.cutoff)
        write_memory(memory, self.run_dir)
        self._record_inputs()
        self._phase("memory", editions=[e["id"] for e in memory["editions"]], threads=len(memory["threads"]), next_edition_number=memory["next_edition_number"])

    def _edition_on_disk_is_usable(self) -> bool:
        """A resumed run reuses edition.json only when it is a valid contract for this run; anything
        else is set aside so the stories are written again rather than the same failure repeating."""
        path = self.run_dir / "edition.json"
        if not path.is_file():
            return False
        try:
            edition = json.loads(path.read_text(encoding="utf8"))
            usable = not validate_edition(edition) and edition["edition"]["id"] == self.edition_id
        except (json.JSONDecodeError, KeyError, TypeError):
            usable = False
        if not usable:
            aside = self.run_dir / f"edition.invalid-{_now().replace(':', '').replace('.', '')}.json"
            path.rename(aside)
            (self.run_dir / "edition-checked.json").unlink(missing_ok=True)
        return usable

    # -- the desk ----------------------------------------------------------------------------------

    _SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")

    def _selection_problems(self, selection: Any, window: dict[str, Any]) -> list[str]:
        """The desk's decision must be complete before a word is written: one lead first, every story
        with a role, a kicker and sources the window holds, and the edition's presentation and note."""
        problems: list[str] = []
        if not isinstance(selection, dict) or not isinstance(selection.get("stories"), list) or not selection["stories"]:
            return ["stories: a selection names at least one story"]
        edition = selection.get("edition")
        if not isinstance(edition, dict) or not isinstance(edition.get("presentation"), dict) or not str(edition.get("note") or "").strip():
            problems.append("edition: presentation and note are required")
        numbers = {a["n"] for a in window["articles"]}
        seen: set[str] = set()
        for i, row in enumerate(selection["stories"]):
            where = f"stories[{i}]"
            if not isinstance(row, dict):
                problems.append(f"{where}: not an object")
                continue
            sid = row.get("id")
            if not isinstance(sid, str) or not self._SLUG.match(sid):
                problems.append(f"{where}.id: not a slug")
            elif sid in seen:
                problems.append(f"{where}.id: {sid} is listed twice")
            seen.add(str(sid))
            if row.get("role") not in ("lead", "secondary", "brief"):
                problems.append(f"{where}.role: not lead, secondary or brief")
            if not str(row.get("kicker") or "").strip():
                problems.append(f"{where}.kicker: missing")
            sources = row.get("sources")
            if not isinstance(sources, list) or not sources:
                problems.append(f"{where}.sources: at least one source")
            else:
                for ref in sources:
                    if isinstance(ref, int) and ref not in numbers:
                        problems.append(f"{where}.sources: [{ref}] is not in the window")
                    elif isinstance(ref, str) and ":" not in ref:
                        problems.append(f"{where}.sources: {ref!r} is not publisher:suffix")
                    elif not isinstance(ref, (int, str)):
                        problems.append(f"{where}.sources: {ref!r} is not a window number")
        roles = [r.get("role") for r in selection["stories"] if isinstance(r, dict)]
        if roles.count("lead") != 1 or roles[0] != "lead":
            problems.append("stories: exactly one lead, first")
        return problems

    def _selection(self) -> dict[str, Any]:
        selection = self._read("selection.json")
        problems = self._selection_problems(selection, self._read("window.json"))
        if problems:
            raise RunFailure("selection_invalid", "the desk's selection is incomplete", {"problems": problems[:10]})
        return selection

    def _desk_on_disk_is_usable(self) -> bool:
        path = self.run_dir / "selection.json"
        if not (path.is_file() and (self.run_dir / "NOTES.md").is_file()):
            return False
        try:
            return not self._selection_problems(json.loads(path.read_text(encoding="utf8")), self._read("window.json"))
        except (json.JSONDecodeError, RunFailure):
            return False

    def _editor(self) -> None:
        """The desk session: it reads, clusters, selects and keeps the log. It writes no copy."""
        if self._desk_on_disk_is_usable():
            self._phase("editor", resumed=True)
            return
        record = self._session(lambda: self.editor("desk", self.run_dir, self._budget(self.policy.limits.editor_minutes)))
        selection = self._selection()
        self._phase("editor", session=record, stories=len(selection["stories"]))

    # -- the writers ---------------------------------------------------------------------------------

    @staticmethod
    def _guidelines_text() -> str:
        """The two writing sections of the architecture document, as text for the brief."""
        text = (REPO / "docs" / "editorial-architecture.md").read_text(encoding="utf8")
        start = text.index("## Writing must remain attached to source evidence")
        end = text.index("## The check", start)
        return text[start:end].strip()

    @staticmethod
    def _golden_story(role: str) -> dict[str, Any]:
        spec = json.loads(GOLDEN_SPEC.read_text(encoding="utf8"))
        story = next(s for s in spec["stories"] if s["role"] == role)
        return {k: v for k, v in story.items() if k not in ("id", "sources")}

    def _budget_for(self, role: str) -> dict[str, Any]:
        budgets = self.policy.budgets
        if role == "lead":
            return {"words": budgets.lead_words, "variants": ["extended", "standard", "short"], "callouts_max": 3}
        if role == "secondary":
            return {"words": budgets.secondary_words, "variants": ["standard", "short"], "callouts_max": 1}
        return {"words": [1, budgets.brief_words], "variants": ["lede"], "callouts_max": 0}

    def _brief(self, row: dict[str, Any], window: dict[str, Any], mode: str, extra: dict[str, Any]) -> dict[str, Any]:
        """Everything a writer gets: this story's evidence, its role and budget, the voice to match,
        and where the guidelines are. Nothing from any other story."""
        by_number = {a["n"]: a for a in window["articles"]}
        articles = []
        for i, ref in enumerate(row["sources"]):
            a = by_number.get(ref) if isinstance(ref, int) else next((x for x in window["articles"] if x["source"] == ref.split(":", 1)[0] and x["source_id"].endswith(ref.split(":", 1)[1])), None)
            if a is None:
                raise RunFailure("selection_invalid", f"{row['id']}: source {ref!r} is not in the window")
            articles.append({
                "ref": ref, "source": a["source"], "status": a["status"], "primary": i == 0, "title": a["title"],
                "description": a.get("description"), "authors": a.get("authors") or [], "categories": a.get("categories") or [],
                "language": a.get("language"), "published_at": a["published_at"], "url": a["url"], "wire": a.get("wire"),
            })
        date = edition_date_for(self.cutoff, self.policy)
        return {
            "schema_version": 1,
            "mode": mode,
            "edition": {"id": self.edition_id, "date": date, "cutoff_at": self.cutoff, "timezone": self.policy.timezone},
            "story": {k: row[k] for k in ("id", "role", "kicker", "kicker_secondary") if k in row},
            "budget": self._budget_for(row["role"]),
            "articles": articles,
            "example": self._golden_story(row["role"]),
            "skill": WRITER_SKILL.read_text(encoding="utf8"),
            "style": (EDITORIAL / "STYLE.md").read_text(encoding="utf8"),
            "guidelines": self._guidelines_text(),
            **extra,
        }

    @staticmethod
    def _write_json_atomic(path: Path, doc: Any) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
        tmp.replace(path)

    @staticmethod
    def _parse_copy(text: str) -> dict[str, Any]:
        """The writer's final message, as JSON: bare, or fenced, or with words around it."""
        candidates = [text.strip()]
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fenced:
            candidates.insert(0, fenced.group(1))
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 < end:
            candidates.append(text[start:end + 1])
        for candidate in candidates:
            try:
                doc = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                return doc
        raise ValueError("the answer is not a JSON object")

    def _record_one_input(self, path: Path) -> None:
        """Add one runner-written file to the record without re-reading the rest: the baseline the
        session guard compares against must not move while sessions are running."""
        with self._inputs_lock:
            record_path = self.run_dir / self.INPUTS_RECORD
            recorded = json.loads(record_path.read_text(encoding="utf8")) if record_path.is_file() else {}
            recorded[path.relative_to(self.run_dir).as_posix()] = _digest(path)
            self._write(self.INPUTS_RECORD, recorded)

    def _write_one(self, row: dict[str, Any], brief_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Run one story's session, twice at most: a second attempt carries the first one's problem.
        Each attempt takes its wall clock from what the run has left at that moment."""
        records: list[dict[str, Any]] = []
        problems: list[str] = []
        path = brief_path
        for attempt in (1, 2):
            if problems:
                # The first brief stays as recorded; the second attempt reads a sibling that carries the
                # problem, recorded as one more input before the session starts.
                brief = json.loads(brief_path.read_text(encoding="utf8"))
                brief["previous_answer_problems"] = problems
                path = brief_path.with_name("brief-retry.json")
                path.write_text(json.dumps(brief, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
                self._record_one_input(path)
            record = self.writer(path, self._budget(self.policy.limits.writer_minutes))
            records.append(record)
            try:
                copy = self._parse_copy(str(record.get("result") or ""))
            except ValueError as exc:
                problems = [str(exc)]
                continue
            problems = validate_story_copy(copy, row["role"])
            if not problems:
                return copy, records
        raise RunFailure("writer_failed", f"{row['id']}: the writer's answer is not usable copy", {"problems": problems[:10], "attempts": len(records)})

    def _write_stories(self, rows: list[dict[str, Any]], mode: str, extra: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Write briefs, then run the sessions a few at a time. The briefs are runner inputs: they are
        recorded before any session starts and checked after all of them end."""
        window = self._read("window.json")
        briefs: dict[str, Path] = {}
        for row in rows:
            story_dir = self.run_dir / "stories" / row["id"]
            story_dir.mkdir(parents=True, exist_ok=True)
            brief_path = story_dir / "brief.json"
            brief_path.write_text(json.dumps(self._brief(row, window, mode, extra.get(row["id"], {})), ensure_ascii=False, indent=1) + "\n", encoding="utf8")
            briefs[row["id"]] = brief_path
        self._record_inputs()
        sessions: dict[str, list[dict[str, Any]]] = {}

        def run_all() -> None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, self.policy.limits.writer_concurrency)) as pool:
                futures = {pool.submit(self._write_one, row, briefs[row["id"]]): row for row in rows}
                failure: BaseException | None = None
                for future in concurrent.futures.as_completed(futures):
                    row = futures[future]
                    try:
                        copy, records = future.result()
                    except BaseException as exc:  # noqa: BLE001 -- the first failure stops the phase; the rest finish.
                        failure = failure or exc
                        continue
                    sessions[row["id"]] = records
                    self._write_json_atomic(self.run_dir / "stories" / row["id"] / "story.json", copy)
                if failure:
                    raise failure

        self._session(run_all)
        return {
            "stories": len(rows),
            "sessions": sum(len(v) for v in sessions.values()),
            "cost_usd": round(sum(r.get("total_cost_usd", 0) or 0 for v in sessions.values() for r in v), 4),
        }

    def _assemble_and_build(self) -> dict[str, Any]:
        """spec.json from the selection and the stories on disk, then the contract, in the runner's hands."""
        selection = self._selection()
        window = self._read("window.json")
        memory = self._read("memory.json")
        feeds = self._read("feeds.json")
        date = edition_date_for(self.cutoff, self.policy)
        stories = []
        for row in selection["stories"]:
            copy = json.loads((self.run_dir / "stories" / row["id"] / "story.json").read_text(encoding="utf8"))
            stories.append(spec_story(row, copy))
        spec = {
            "edition": {
                "id": self.edition_id,
                "number": memory["next_edition_number"],
                "name": f"{dt.date.fromisoformat(date):%A} edition",
                "date": date,
                "cutoff_at": self.cutoff,
                "checked_from": window["window"]["since"],
                "input_id": window["bundle"]["input_id"],
                "presentation": selection["edition"]["presentation"],
                "note": selection["edition"]["note"],
            },
            "stories": stories,
        }
        self._write("spec.json", spec)
        try:
            bundle = load_bundle(self.run_dir / "bundle")
        except BundleError as exc:
            raise RunFailure("bundle_invalid", str(exc)) from exc
        edition = build_edition(
            spec, bundle, feeds, window=window, memory=memory,
            scoring=set(self.policy.scoring_publishers), corroborating=set(self.policy.corroborating_publishers),
            wire_agencies=self.policy.wire_agencies,
        )
        write_edition(edition, self.run_dir / "edition.json")
        return edition

    def _build_with_repair(self, mode: str, extra: dict[str, dict[str, Any]], rewritten: set[str]) -> dict[str, Any]:
        """Build; when the build names a story's copy as the problem, that story is written once more
        with the problem in its brief, then the build runs again. Anything else fails the run."""
        selection = self._selection()
        rows = {r["id"]: r for r in selection["stories"]}
        for _ in range(len(rows) + 1):
            try:
                return self._assemble_and_build()
            except BuildError as exc:
                message = str(exc)
                story_id = message.split(":", 1)[0]
                if story_id in rows and story_id not in rewritten:
                    rewritten.add(story_id)
                    self._write_stories([rows[story_id]], mode, {story_id: {**extra.get(story_id, {}), "build_problem": message}})
                    continue
                raise RunFailure("contract_invalid", "the stories do not build into a valid edition", {"problem": message}) from exc
        raise RunFailure("contract_invalid", "the stories do not build into a valid edition", {})

    def _write_copy(self) -> None:
        """One session per story, each with that story's evidence alone, then the spec and the contract."""
        if self._edition_on_disk_is_usable():
            self._phase("write", resumed=True)
            return
        selection = self._selection()
        window = self._read("window.json")
        todo = [row for row in selection["stories"] if not self._story_on_disk_is_usable(row, window)]
        summary = self._write_stories(todo, "write", {}) if todo else {"stories": 0, "sessions": 0, "cost_usd": 0}
        self._build_with_repair("write", {}, set())
        self._phase("write", **summary, resumed_stories=len(selection["stories"]) - len(todo))

    def _story_on_disk_is_usable(self, row: dict[str, Any], window: dict[str, Any]) -> bool:
        """A story written by an earlier attempt is reused only when it is valid copy for its role and
        was written from the brief this run would write now; anything else is set aside and the story
        is written again."""
        story_dir = self.run_dir / "stories" / row["id"]
        story_path, brief_path = story_dir / "story.json", story_dir / "brief.json"
        if not (story_path.is_file() and brief_path.is_file()):
            return False
        usable = False
        try:
            same_brief = json.loads(brief_path.read_text(encoding="utf8")) == self._brief(row, window, "write", {})
            copy = json.loads(story_path.read_text(encoding="utf8"))
            usable = same_brief and not validate_story_copy(copy, row["role"])
        except (json.JSONDecodeError, RunFailure, TypeError):
            usable = False
        if not usable:
            story_path.rename(story_dir / f"story.invalid-{_now().replace(':', '').replace('.', '')}.json")
        return usable

    def _rewrite(self, story_ids: list[str]) -> None:
        """A send-back: only the named stories are written again, with their strikes in the brief."""
        selection = self._selection()
        send_back = self._read("send-back.json")
        check_input_doc = self._read("check-input.json")
        text_by = {(s["id"], v["location"], v["sentence"]): v["text"] for s in check_input_doc["stories"] for v in s["sentences"]}
        extra: dict[str, dict[str, Any]] = {}
        for sid in story_ids:
            strikes = [
                {"location": v["location"], "sentence": v["sentence"], "text": text_by.get((sid, v["location"], v["sentence"])), "reason": v.get("reason")}
                for v in send_back["strikes"] if v["story"] == sid
            ]
            previous = json.loads((self.run_dir / "stories" / sid / "story.json").read_text(encoding="utf8"))
            extra[sid] = {"strikes": strikes, "previous": previous}
            lookups_path = self.run_dir / "stories" / sid / "lookups.json"
            if lookups_path.is_file():
                extra[sid]["lookups"] = [{k: v for k, v in row.items() if k in ("term", "definition", "requested", "status", "title")} for row in json.loads(lookups_path.read_text(encoding="utf8"))]
        rows = [r for r in selection["stories"] if r["id"] in story_ids]
        self._write_stories(rows, "revise", extra)
        self._build_with_repair("revise", extra, set())

    def _verdicts_on_disk_for(self, check_input_doc: dict[str, Any]) -> bool:
        """True when a previous, interrupted run already had this exact check input checked, and the
        verdicts it left are complete and valid; invalid verdicts are never reused, so a retry asks
        the checker again instead of failing the same way."""
        previous = self.run_dir / "check-input.json"
        verdicts = self.run_dir / "verdicts.json"
        if not (previous.is_file() and verdicts.is_file()):
            return False
        try:
            if json.loads(previous.read_text(encoding="utf8")) != check_input_doc:
                return False
            doc = without_nulls(json.loads(verdicts.read_text(encoding="utf8")))
            if validate_verdicts(doc) or doc.get("edition_id") != check_input_doc["edition_id"]:
                return False
            return not any(coverage_problems(check_input_doc, doc).values())
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return False

    def _references(self, edition: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """For every explanation a writer declared, the Wikipedia summary that should confirm it, fetched
        by the runner and kept beside the story as lookups.json. A lookup that fails leaves no reference
        row, and the checker then treats the explanation as the unsupported fact it is."""
        references: dict[str, list[dict[str, Any]]] = {}
        for story in edition["stories"]:
            story_dir = self.run_dir / "stories" / story["id"]
            story_path = story_dir / "story.json"
            if not story_path.is_file():
                continue
            definitions = json.loads(story_path.read_text(encoding="utf8")).get("definitions") or []
            if not definitions:
                continue
            lookups_path = story_dir / "lookups.json"
            existing = {}
            if lookups_path.is_file():
                try:
                    existing = {row["requested"]: row for row in json.loads(lookups_path.read_text(encoding="utf8"))}
                except (json.JSONDecodeError, KeyError, TypeError):
                    existing = {}
            rows = []
            for definition in definitions:
                title = definition["wikipedia"]
                row = existing.get(title)
                if row is None or row.get("status") != "found":
                    row = self.lookup(title)
                    row["fetched_at"] = _now()
                rows.append({**row, "term": definition["term"], "definition": definition["definition"]})
            self._write_json_atomic(lookups_path, rows)
            references[story["id"]] = rows
        return references

    def _check_once(self, edition: dict[str, Any], final: bool, resume: bool = False) -> dict[str, Any]:
        window = self._read("window.json")
        check_input_doc = check_input(edition, window, self._references(edition))
        if resume and self._verdicts_on_disk_for(check_input_doc):
            self.resumed_checks += 1
            self._record_inputs()
        else:
            self._write("check-input.json", check_input_doc)
            self._record_inputs()
            (self.run_dir / "verdicts.json").unlink(missing_ok=True)
            self._session(lambda: self.checker(self.run_dir, self._budget(self.policy.limits.checker_minutes)))
        verdicts = without_nulls(self._read("verdicts.json"))
        self._write("verdicts.json", verdicts)
        if verdicts.get("edition_id") != edition["edition"]["id"]:
            raise RunFailure("verdicts_invalid", "the verdicts name a different edition")
        try:
            coverage = coverage_problems(check_input_doc, verdicts)
        except (KeyError, TypeError) as exc:
            raise RunFailure("verdicts_invalid", f"the verdicts are malformed: {exc}") from exc
        if any(coverage.values()):
            raise RunFailure("verdicts_invalid", "the verdicts do not cover the check input sentence for sentence, once each", {k: v[:20] for k, v in coverage.items()})
        try:
            result = apply_verdicts(edition, verdicts, min_words=self.policy.limits.story_stands_min_words, final=final)
        except ValueError as exc:
            raise RunFailure("verdicts_invalid", str(exc)) from exc
        self._write("send-back.json", {
            "schema_version": 1, "edition_id": edition["edition"]["id"], "send_back": result["send_back"], "fallen": result["fallen"],
            "stories": {sid: r for sid, r in result["stories"].items() if not r["stands"]},
            "strikes": [{"story": s["id"], **v} for s in verdicts["stories"] for v in s["sentences"] if v["verdict"] == "unsupported"],
        })
        return result

    def _check(self) -> None:
        edition = self._read("edition.json")
        self.resumed_checks = 0
        rounds = 0
        # Only the first round may pick up an interrupted run's verdicts; a send-back is always re-checked.
        result = self._check_once(edition, final=False, resume=True)
        rounds += 1
        sent_back = list(result["send_back"])
        for _ in range(self.policy.limits.check_send_backs):
            if not result["send_back"]:
                break
            before = edition
            self._rewrite(list(result["send_back"]))
            edition = self._read("edition.json")
            problems = validate_edition(edition)
            if problems:
                raise RunFailure("contract_invalid", "the revised edition fails the contract", {"problems": problems[:10]})
            if edition["edition"]["id"] != self.edition_id:
                raise RunFailure("conflict", "the send-back changed the edition id", {"edition": edition["edition"]["id"]})
            # A send-back may change only the stories that were sent back.
            untouched = {s["id"]: s for s in before["stories"] if s["id"] not in result["send_back"]}
            after = {s["id"]: s for s in edition["stories"]}
            changed = sorted(sid for sid, story in untouched.items() if after.get(sid) != story)
            missing = sorted(sid for sid in untouched if sid not in after)
            if changed or missing:
                raise RunFailure("send_back_overreach", "the send-back changed stories that were not sent back", {"changed": changed[:20], "missing": missing[:20]})
            result = self._check_once(edition, final=True)
            rounds += 1
        if result["send_back"]:
            # The send-back budget is spent: the stories that still do not stand fall to a headline.
            verdicts = self._read("verdicts.json")
            result = apply_verdicts(edition, verdicts, min_words=self.policy.limits.story_stands_min_words, final=True)
        problems = validate_edition(result["edition"])
        if problems:
            raise RunFailure("contract_invalid", "the struck edition fails the contract", {"problems": problems[:10]})
        self._write("edition-checked.json", result["edition"])
        self._phase("check", rounds=rounds, struck=result["struck"], send_back=sent_back, fallen=result["fallen"], resumed=self.resumed_checks > 0)

    def _preflight(self) -> None:
        self.publisher("validate", "--edition", str(self.run_dir / "edition-checked.json"), timeout=self._budget(2))
        self._phase("preflight", valid=True)

    def _publish(self) -> None:
        """The web edition, and the device page when the desk config asks for it. The desk makes no
        device decisions either way: block 3 fits the page from the same contract, and a device failure
        degrades the publish to web-only rather than stopping it."""
        args = ["--edition", str(self.run_dir / "edition-checked.json"), "--publish-root", str(self.publish_root)]
        if not self.device:
            args.append("--skip-device")
        if self.dry_run:
            args.append("--dry-run")
        result = self.publisher("publish", *args, timeout=self._budget(15))
        self.status["published"] = {
            "edition": str(self.run_dir / "edition-checked.json"),
            "status": result.get("status"),
            "device_status": result.get("device_status"),
            "bundle": result.get("bundle"),
        }
        self._phase("publish", status=result.get("status"), device_status=result.get("device_status"))

    # Files the runner writes and the sessions only read: the evidence the checker is judged against.
    INPUT_FILES = ("window.json", "window.md", "window-linked.md", "memory.json", "feeds.json", "check-input.json")
    INPUTS_RECORD = "inputs.json"
    # What the sessions produce. When the evidence is found changed, these go with it: they were
    # made beside evidence that can no longer be trusted.
    MODEL_OUTPUTS = (
        "clusters.json", "clusters-checked.json", "ranking.json", "selection.json", "spec.json",
        "edition.json", "edition-checked.json", "NOTES.md", "verdicts.json", "send-back.json", "stories",
    )

    def _input_digests(self) -> dict[str, str | None]:
        digests: dict[str, str | None] = {name: _digest(self.run_dir / name) for name in self.INPUT_FILES}
        bundle = self.run_dir / "bundle"
        if bundle.is_dir():
            for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
                digests[path.relative_to(self.run_dir).as_posix()] = _digest(path)
        for pattern in ("*/brief*.json", "*/lookups.json"):
            for path in sorted((self.run_dir / "stories").glob(pattern)):
                digests[path.relative_to(self.run_dir).as_posix()] = _digest(path)
        return digests

    def _record_inputs(self) -> None:
        """The runner's record of what it wrote. A session and a later run are both judged against it."""
        present = {k: v for k, v in self._input_digests().items() if v is not None}
        self._write(self.INPUTS_RECORD, present)

    def _verify_inputs(self) -> None:
        """At the start of a run: the inputs on disk must be the ones the runner recorded. Anything
        else, however it got there, is quarantined with the artifacts made beside it, so the run
        rebuilds from the verified source rather than adopting changed bytes as its baseline."""
        record_path = self.run_dir / self.INPUTS_RECORD
        if not record_path.is_file():
            self._phase("inputs", recorded=False)
            return
        recorded = json.loads(record_path.read_text(encoding="utf8"))
        current = self._input_digests()
        modified = sorted(p for p, digest in recorded.items() if current.get(p) is not None and current.get(p) != digest)
        if modified:
            quarantine = self._quarantine()
            raise RunFailure("input_modified", "the run's inputs changed since the runner wrote them; they are quarantined and the run starts again", {"paths": modified[:20], "quarantine": str(quarantine)})
        self._phase("inputs", recorded=True, files=len(recorded))

    def _quarantine(self) -> Path:
        """Move every input and every model output of this run aside, keeping them for inspection."""
        target = self.run_dir / f"quarantine-{_now().replace(':', '').replace('.', '')}"
        target.mkdir()
        names = [*self.INPUT_FILES, "bundle", *self.MODEL_OUTPUTS, self.INPUTS_RECORD]
        for name in names:
            path = self.run_dir / name
            if path.exists():
                path.rename(target / name)
        return target

    def _protected_state(self) -> dict[str, str | None]:
        """Desk state outside git that a session must not touch: the thread registry."""
        try:
            key = self.registry.relative_to(self.repo).as_posix()
        except ValueError:
            key = str(self.registry)
        return {key: _digest(self.registry)}

    def _tree_digests(self) -> dict[str, str | None]:
        """The working tree's changed paths with their content, plus protected state outside git, so a
        session rewriting a file the owner already had open, or reverting it to the committed text,
        or touching desk state git ignores, is caught."""
        try:
            run_prefix = self.run_dir.relative_to(self.repo).as_posix() + "/"
        except ValueError:
            run_prefix = None
        digests = {p: _digest(self.repo / p) for p in self.stray_changes() if run_prefix is None or not p.startswith(run_prefix)}
        digests.update(self._protected_state())
        return digests

    def _session(self, call: Callable[[], Any]) -> Any:
        """Run a model session and refuse to go on if it wrote where it may not.

        Two comparisons bracket the session, and both run whatever the session's outcome. Outside the
        run directory, the set of changed paths and their contents must be the same afterwards (a path
        that vanished from the changed set was reverted, which counts). Inside it, the runner-owned
        inputs must be byte-identical to the runner's record; if not, they and everything made beside
        them are quarantined so the next run rebuilds from the verified source."""
        tree_before = self._tree_digests()
        failure: BaseException | None = None
        result = None
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 -- checked below, then re-raised.
            failure = exc
        tree_after = self._tree_digests()
        missing = object()
        stray = sorted(p for p in set(tree_before) | set(tree_after) if tree_before.get(p, missing) != tree_after.get(p, missing))
        if stray:
            details: dict[str, Any] = {"paths": stray[:20]}
            if isinstance(failure, RunFailure):
                details["after"] = failure.error_type
            elif failure:
                details["after"] = f"{type(failure).__name__}: {failure}"
            raise RunFailure("stray_edits", "the session wrote outside the run directory; sessions may only write there", details)
        record_path = self.run_dir / self.INPUTS_RECORD
        recorded = json.loads(record_path.read_text(encoding="utf8")) if record_path.is_file() else {}
        current = self._input_digests()
        modified = sorted(p for p, digest in recorded.items() if current.get(p) != digest)
        if modified:
            quarantine = self._quarantine()
            raise RunFailure("input_modified", "the session changed the runner's inputs; the evidence must stay as it was frozen, so it and the session's work are quarantined", {"paths": modified[:20], "quarantine": str(quarantine)})
        if failure:
            raise failure
        return result

    def _receipt(self) -> None:
        if self.dry_run:
            self._phase("receipt", skipped=True)
            return
        result = self.publisher("receipt", "--publish-root", str(self.publish_root), "--edition", self.edition_id, timeout=self._budget(2))
        if not result.get("activated"):
            raise RunFailure("not_activated", "block 3 holds no activated receipt for the edition", {"result": result})
        self.status["published"]["receipt"] = {"sequence": result.get("activation", {}).get("sequence"), "manifest_sha256": result.get("manifest_sha256"), "web_story_ids": result["receipt"]["web"]["story_ids"]}
        self._phase("receipt", activated=True, web_stories=len(result["receipt"]["web"]["story_ids"]))

    def _threads(self) -> None:
        """Advance the thread registry from the web set of an activated receipt, never earlier."""
        if self.dry_run:
            self._phase("threads", skipped=True)
            return
        published = set(self.status["published"]["receipt"]["web_story_ids"])
        selection = self._read("selection.json") if (self.run_dir / "selection.json").is_file() else {"stories": []}
        checked = self._read("clusters-checked.json") if (self.run_dir / "clusters-checked.json").is_file() else {"clusters": []}
        ranking = self._read("ranking.json") if (self.run_dir / "ranking.json").is_file() else {"candidates": []}
        clusters = {c["id"]: c for c in checked["clusters"]}
        breadth = {c["id"]: c.get("breadth", 0) for c in ranking["candidates"]}
        registry = load_registry(self.registry)
        by_id = {t["id"]: t for t in registry["threads"]}
        date = edition_date_for(self.cutoff, self.policy)
        touched = 0
        for story in selection["stories"]:
            if story["id"] not in published:
                continue
            cluster = clusters.get(story.get("cluster"))
            thread = (cluster or {}).get("thread")
            if not thread:
                continue
            if "new" in thread:
                tid, description = thread["new"]["id"], thread["new"]["description"]
            else:
                tid, description = thread["id"], None
            row = by_id.get(tid)
            if row is None:
                row = {"id": tid, "description": description or tid, "opened_edition_id": self.edition_id, "last_edition_id": None, "last_seen_date": date, "peak_breadth": 0, "story_ids": []}
                by_id[tid] = row
                registry["threads"].append(row)
            row["last_edition_id"] = self.edition_id
            row["last_seen_date"] = date
            row["peak_breadth"] = max(row.get("peak_breadth", 0), breadth.get(story.get("cluster"), 0))
            if story["id"] not in row["story_ids"]:
                row["story_ids"].append(story["id"])
            touched += 1
        save_registry(self.registry, registry)
        self._phase("threads", touched=touched, total=len(registry["threads"]))

    def _notify_failure(self) -> None:
        if not self.notifier:
            return
        failure = self.status["failure"] or {}
        subject = f"Copenhagen Daily: {self.edition_id} failed in {failure.get('phase')}"
        if self.status.get("published"):
            standing = (
                "The edition is activated in the newsroom's store but the steps after it did not complete, so the site may still show "
                "the previous edition. A retry resumes from the failed step without publishing again."
            )
        else:
            standing = "The last activated edition stays in place. A retry runs later in the morning; after that, read the status and rerun by hand."
        body = (
            f"Edition {self.edition_id} stopped in phase {failure.get('phase')}: {failure.get('type')}.\n"
            f"{failure.get('message')}\n\nRun directory: {self.run_dir}\nStatus: {self.run_dir / 'status.json'}\n{standing}"
        )
        try:
            self.notifier(subject, body)
        except Exception as exc:  # noqa: BLE001 -- a failed notification must not hide the failure it reports.
            sys.stderr.write(f"notification failed: {exc}\n")

    def _deliver(self) -> None:
        if self.dry_run or self.deliverer is None:
            self._phase("deliver", skipped=True)
            return
        result = self.deliverer(self.publish_root)
        self._phase("deliver", **(result or {}))

    def _archive(self) -> None:
        if self.dry_run or not self.commit:
            self._phase("archive", skipped=True)
            return
        try:
            relative = self.run_dir.relative_to(self.repo)
        except ValueError:
            self._phase("archive", skipped=True, reason="run directory outside the repository")
            return
        # The status committed with the run is the final one, so the outcome is settled here.
        self.status["outcome"] = "published"
        self.status["phases"].append({"name": "archive", "finished_at": _now(), "committed": len([n for n in SMALL_FILES if (self.run_dir / n).exists()])})
        self._write_status()
        paths = [str(relative / name) for name in SMALL_FILES if (self.run_dir / name).exists()]
        self.git("add", *paths)
        # Only the run's own files: anything else the owner had staged stays staged, uncommitted.
        self.git("commit", "-q", "--only", "-m", f"Archive the {self.edition_id} edition", "--", *paths)


def run_edition(args: Any, policy: Policy) -> dict[str, Any]:
    config = load_desk_config()
    cutoff = args.cutoff or cutoff_for(dt.datetime.now(zoneinfo.ZoneInfo(policy.timezone)).date().isoformat(), policy)
    if "." not in cutoff:
        cutoff = cutoff.replace("Z", ".000000Z")
    edition_id = args.edition or f"{edition_date_for(cutoff, policy)}-{policy.schedule.edition}"
    publish_root = Path(args.publish_root or config["publish_root"])
    if not publish_root.is_absolute():
        publish_root = REPO / publish_root
    notifier = lambda subject, body: notify(subject, body, config.get("notify") or {})  # noqa: E731
    auth = ClaudeAuth(notifier=notifier, edition_id=edition_id)
    codex_auth = CodexAuth(notifier=notifier, edition_id=edition_id)
    runner = Runner(
        policy=policy,
        run_dir=RUNS / edition_id,
        edition_id=edition_id,
        cutoff=cutoff,
        publish_root=publish_root,
        registry=VAR / "threads.json",
        editor=lambda mode, run_dir, timeout: invoke_editor(mode, run_dir, timeout, config, max_turns=policy.limits.editor_turns, auth=auth),
        writer=lambda brief, timeout: invoke_writer(brief, timeout, config, max_turns=policy.limits.writer_turns, auth=auth),
        checker=lambda run_dir, timeout: invoke_checker(run_dir, timeout, {**config, "checker": args.checker or config.get("checker", "claude")}, max_turns=policy.limits.checker_turns, auth=auth, codex_auth=codex_auth),
        collect=config.get("collect_before_export", True) and not args.no_collect,
        dry_run=args.dry_run,
        commit=config.get("commit_runs", True),
        notifier=notifier,
        deliverer=lambda root: deliver(root, config.get("delivery") or {}),
        device=bool(config.get("device", False)),
        retry=getattr(args, "retry", False),
    )
    return runner.run()
