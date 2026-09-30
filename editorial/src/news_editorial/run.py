"""The runner: one edition end to end, deterministic steps around two bounded sessions.

The output is the web edition, and, when the desk config asks, block 3's page for the kitchen screen,
fitted from the same contract; the contract's device fields are filled mechanically by `build`.

Every phase ends in a file in the run directory and a line in status.json. Nothing retries a model
step blindly; a failure keeps the last activated edition in place and says why.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
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
from .bundle import BundleError, load_bundle
from .clusters import check_clusters, write_checked  # noqa: F401 -- re-exported for the desk
from .contract import validate_edition
from .deliver import deliver, push_device
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
EDITOR_ACTIONS = ("check-clusters", "score", "build")
# What the archive commits: the desk's own work. The check input and the verdicts stay out of git
# because they quote the publishers' text; they remain in the run directory on disk.
SMALL_FILES = [
    "feeds.json", "memory.json", "clusters.json", "clusters-checked.json", "ranking.json", "selection.json", "spec.json",
    "edition.json", "send-back.json", "edition-checked.json",
    "NOTES.md", "status.json",
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


def _headless(command: list[str], cwd: Path, timeout: int, name: str, run_dir: Path, limit: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = blocks.run_in_group(command, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _session_record(run_dir, name, {"command": command[:2], "timed_out_after_s": timeout})
        raise RunFailure(f"{limit}_timeout", f"{name} ran past its wall clock of {timeout}s", {"limit": limit}) from exc
    elapsed = round(time.monotonic() - started, 1)
    if proc.stderr:
        sys.stderr.write(proc.stderr[-4000:])
    record: dict[str, Any] = {"command": command[:2], "exit_code": proc.returncode, "elapsed_s": elapsed}
    try:
        result = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"stdout": proc.stdout[-4000:]}
    except json.JSONDecodeError:
        result = {"stdout": proc.stdout[-4000:]}
    for key in ("session_id", "num_turns", "duration_ms", "total_cost_usd", "is_error", "subtype", "permission_denials", "result"):
        if key in result:
            record[key] = result[key]
    _session_record(run_dir, name, record)
    if proc.returncode != 0 or result.get("is_error"):
        raise RunFailure(f"{name.split('-')[0]}_failed", f"{name} exited {proc.returncode}", {"record": record})
    return record


def invoke_editor(mode: str, run_dir: Path, timeout: int, config: dict[str, Any] | None = None, max_turns: int | None = None) -> dict[str, Any]:
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
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"editor-{mode}-{_now()[:19]}", run_dir=run_dir, limit="editor")


def invoke_checker(run_dir: Path, timeout: int, config: dict[str, Any] | None = None, max_turns: int | None = None) -> dict[str, Any]:
    config = config or load_desk_config()
    tool = config.get("checker", "claude")
    if tool == "codex":
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
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"checker-{_now()[:19]}", run_dir=run_dir, limit="checker")


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
        checker: Callable[[Path, int], dict[str, Any]] = invoke_checker,
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
        device_pusher: Callable[[Path], dict[str, Any]] | None = None,
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
        self.device_pusher = device_pusher
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
                ("check", self._check),
                ("preflight", self._preflight),
                ("publish", self._publish),
                ("receipt", self._receipt),
                ("threads", self._threads),
                ("deliver", self._deliver),
                ("device_push", self._push_device),
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

    BEFORE_ACTIVATION = ("inputs", "collect", "window", "memory", "editor", "check", "preflight", "publish")

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
        else is set aside so the editor runs again rather than the same failure repeating forever."""
        path = self.run_dir / "edition.json"
        if not (path.is_file() and (self.run_dir / "NOTES.md").is_file()):
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

    def _editor(self) -> None:
        if self._edition_on_disk_is_usable():
            self._phase("editor", resumed=True)
        else:
            record = self._session(lambda: self.editor("edition", self.run_dir, self._budget(self.policy.limits.editor_minutes)))
            self._phase("editor", session=record)
        edition = self._read("edition.json")
        problems = validate_edition(edition)
        if problems:
            raise RunFailure("contract_invalid", "the editor's edition fails the contract", {"problems": problems[:10]})
        if edition["edition"]["id"] != self.edition_id:
            raise RunFailure("conflict", "the edition id does not match the run", {"edition": edition["edition"]["id"]})

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

    def _check_once(self, edition: dict[str, Any], final: bool, resume: bool = False) -> dict[str, Any]:
        window = self._read("window.json")
        check_input_doc = check_input(edition, window)
        if resume and self._verdicts_on_disk_for(check_input_doc):
            self.resumed_checks += 1
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
            self._session(lambda: self.editor("send-back", self.run_dir, self._budget(self.policy.limits.editor_minutes)))
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
    INPUT_FILES = ("window.json", "window.md", "memory.json", "feeds.json", "check-input.json")
    INPUTS_RECORD = "inputs.json"
    # What the sessions produce. When the evidence is found changed, these go with it: they were
    # made beside evidence that can no longer be trusted.
    MODEL_OUTPUTS = (
        "clusters.json", "clusters-checked.json", "ranking.json", "selection.json", "spec.json",
        "edition.json", "edition-checked.json", "NOTES.md", "verdicts.json", "send-back.json",
    )

    def _input_digests(self) -> dict[str, str | None]:
        digests: dict[str, str | None] = {name: _digest(self.run_dir / name) for name in self.INPUT_FILES}
        bundle = self.run_dir / "bundle"
        if bundle.is_dir():
            for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
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

    def _push_device(self) -> None:
        """Copy the device page to the kitchen screen's host. The paper is already out, so a failure here
        is recorded and reported, never raised."""
        published = (self.status.get("published") or {}).get("device_status")
        if self.dry_run or self.device_pusher is None or published != "published":
            self._phase("device_push", skipped=True, reason="dry run" if self.dry_run else "no device page")
            return
        try:
            result = self.device_pusher(self.publish_root)
        except Exception as exc:  # noqa: BLE001 -- the paper is published; the push is best effort.
            self._phase("device_push", failed=True, error=str(exc))
            if self.notifier:
                try:
                    self.notifier(f"Copenhagen Daily: the device page was not pushed for {self.edition_id}",
                                  f"The web edition is live. Pushing the device page failed: {exc}")
                except Exception as note:  # noqa: BLE001
                    sys.stderr.write(f"notification failed: {note}\n")
            return
        self._phase("device_push", **(result or {}))

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
    runner = Runner(
        policy=policy,
        run_dir=RUNS / edition_id,
        edition_id=edition_id,
        cutoff=cutoff,
        publish_root=publish_root,
        registry=VAR / "threads.json",
        editor=lambda mode, run_dir, timeout: invoke_editor(mode, run_dir, timeout, config, max_turns=policy.limits.editor_turns),
        checker=lambda run_dir, timeout: invoke_checker(run_dir, timeout, {**config, "checker": args.checker or config.get("checker", "claude")}, max_turns=policy.limits.checker_turns),
        collect=config.get("collect_before_export", True) and not args.no_collect,
        dry_run=args.dry_run,
        commit=config.get("commit_runs", True),
        notifier=lambda subject, body: notify(subject, body, config.get("notify") or {}),
        deliverer=lambda root: deliver(root, config.get("delivery") or {}),
        device=bool(config.get("device", False)),
        device_pusher=lambda root: push_device(root, config.get("device_push") or {}),
        retry=getattr(args, "retry", False),
    )
    return runner.run()
