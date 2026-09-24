"""The runner: one edition end to end, deterministic steps around two bounded sessions.

Every phase ends in a file in the run directory and a line in status.json. Nothing retries a model
step blindly; a failure keeps the last activated edition in place and says why.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
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
from .memory import build_memory, load_registry, save_registry, write_memory
from .paths import EDITORIAL, REPO, RUNS, VAR, VERDICTS_SCHEMA_PATH
from .policy import Policy
from .verdicts import apply_verdicts, check_input
from .window import build_window, write_window

DESK_CONFIG = EDITORIAL / "config" / "desk.yaml"
SMALL_FILES = [
    "feeds.json", "clusters.json", "clusters-checked.json", "ranking.json", "selection.json", "spec.json",
    "edition.json", "check-input.json", "verdicts.json", "send-back.json", "edition-checked.json",
    "fit-repair.json", "NOTES.md", "status.json",
]


class RunFailure(Exception):
    def __init__(self, error_type: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


def load_desk_config(path: Path = DESK_CONFIG) -> dict[str, Any]:
    with path.open(encoding="utf8") as handle:
        return yaml.safe_load(handle)


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
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
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


def invoke_editor(mode: str, run_dir: Path, timeout: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_desk_config()
    wrapper = EDITORIAL / "edit_news.sh"
    prompt = (
        f"Read {REPO / 'skills' / 'editorial-desk' / 'SKILL.md'} and follow it exactly. "
        f"Run directory: {run_dir}. Edition id: {run_dir.name}. Mode: {mode}."
    )
    command = [
        config.get("editor_command", "claude"), "-p", prompt,
        "--output-format", "json", "--permission-mode", "acceptEdits",
        "--allowedTools", f"Bash({wrapper} *)",
        "--disallowedTools", "WebFetch,WebSearch",
        "--no-session-persistence",
    ]
    if config.get("editor_model"):
        command += ["--model", config["editor_model"]]
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"editor-{mode}-{_now()[:19]}", run_dir=run_dir, limit="editor")


def invoke_checker(run_dir: Path, timeout: int, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_desk_config()
    tool = config.get("checker", "claude")
    if tool == "codex":
        prompt = (
            f"Read {EDITORIAL / 'VERIFIER.md'} and follow it exactly. Read {run_dir / 'check-input.json'}. "
            "Your final message is the verdicts JSON and nothing else."
        )
        command = [
            config.get("codex_command", "codex"), "exec", "--skip-git-repo-check", "-s", "read-only", "--ephemeral",
            "--output-schema", str(VERDICTS_SCHEMA_PATH), "-o", str(run_dir / "verdicts.json"), "-C", str(run_dir),
        ]
        if config.get("checker_model"):
            command += ["-m", config["checker_model"]]
        command.append(prompt)
    else:
        prompt = f"Read {REPO / 'skills' / 'editorial-checker' / 'SKILL.md'} and follow it exactly. Run directory: {run_dir}."
        command = [
            config.get("editor_command", "claude"), "-p", prompt,
            "--output-format", "json", "--permission-mode", "acceptEdits",
            "--disallowedTools", "WebFetch,WebSearch,Bash",
            "--no-session-persistence",
        ]
        if config.get("checker_model"):
            command += ["--model", config["checker_model"]]
    return _headless(command, cwd=run_dir, timeout=timeout, name=f"checker-{_now()[:19]}", run_dir=run_dir, limit="checker")


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True)


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
        collect: bool = True,
        dry_run: bool = False,
        commit: bool = True,
        repo: Path = REPO,
    ):
        self.repo = repo
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
            if previous.get("outcome") == "published":
                raise RunFailure("conflict", f"{self.edition_id} is already published; an edition id is used once", {"run": str(self.run_dir)})
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_status()
        phase = "start"
        try:
            for phase, step in (
                ("collect", self._collect),
                ("window", self._window),
                ("memory", self._memory),
                ("editor", self._editor),
                ("check", self._check),
                ("preflight", self._preflight),
                ("fit", self._fit),
                ("publish", self._publish),
                ("receipt", self._receipt),
                ("threads", self._threads),
                ("archive", self._archive),
            ):
                step()
        except (RunFailure, BlockError) as exc:
            self.status["outcome"] = "failed"
            self.status["failure"] = {"phase": phase, "type": exc.error_type, "message": str(exc), "details": exc.details}
            self._write_status()
            return self.status
        self.status["outcome"] = "dry_run" if self.dry_run else "published"
        self._write_status()
        return self.status

    def _collect(self) -> None:
        if not self.collect:
            self._phase("collect", skipped=True)
            return
        result = self.ingest("collect", "--once", timeout=self._budget(15))
        self._phase("collect", status=result.get("status"))

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
        self._phase("window", articles=len(window["articles"]), feeds=len(feeds), failed_feeds=sum(1 for f in feeds if f["outcome"] != "checked"))

    def _previous_cutoff(self) -> str | None:
        memory = build_memory(self.publish_root, self.registry, self.policy, cutoff=self.cutoff)
        return memory["previous_cutoff_at"]

    def _memory(self) -> None:
        memory = build_memory(self.publish_root, self.registry, self.policy, cutoff=self.cutoff)
        write_memory(memory, self.run_dir)
        self._phase("memory", editions=[e["id"] for e in memory["editions"]], threads=len(memory["threads"]), next_edition_number=memory["next_edition_number"])

    def _editor(self) -> None:
        if (self.run_dir / "edition.json").is_file() and (self.run_dir / "NOTES.md").is_file():
            self._phase("editor", resumed=True)
        else:
            record = self.editor("edition", self.run_dir, self._budget(self.policy.limits.editor_minutes))
            self._phase("editor", session=record)
        edition = self._read("edition.json")
        problems = validate_edition(edition)
        if problems:
            raise RunFailure("contract_invalid", "the editor's edition fails the contract", {"problems": problems[:10]})
        if edition["edition"]["id"] != self.edition_id:
            raise RunFailure("conflict", "the edition id does not match the run", {"edition": edition["edition"]["id"]})

    def _check_once(self, edition: dict[str, Any], final: bool) -> dict[str, Any]:
        window = self._read("window.json")
        self._write("check-input.json", check_input(edition, window))
        (self.run_dir / "verdicts.json").unlink(missing_ok=True)
        self.checker(self.run_dir, self._budget(self.policy.limits.checker_minutes))
        verdicts = self._read("verdicts.json")
        if verdicts.get("edition_id") != edition["edition"]["id"]:
            raise RunFailure("verdicts_invalid", "the verdicts name a different edition")
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
        rounds = 0
        result = self._check_once(edition, final=False)
        rounds += 1
        sent_back = list(result["send_back"])
        for _ in range(self.policy.limits.check_send_backs):
            if not result["send_back"]:
                break
            self.editor("send-back", self.run_dir, self._budget(self.policy.limits.editor_minutes))
            edition = self._read("edition.json")
            problems = validate_edition(edition)
            if problems:
                raise RunFailure("contract_invalid", "the revised edition fails the contract", {"problems": problems[:10]})
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
        self._phase("check", rounds=rounds, struck=result["struck"], send_back=sent_back, fallen=result["fallen"])

    def _preflight(self) -> None:
        self.publisher("validate", "--edition", str(self.run_dir / "edition-checked.json"), timeout=self._budget(2))
        self._phase("preflight", valid=True)

    def _fit(self) -> None:
        rounds = 0
        while True:
            try:
                result = self.publisher("fit", "--edition", str(self.run_dir / "edition-checked.json"), timeout=self._budget(10))
                self._phase("fit", rounds=rounds, composition=result.get("composition"))
                return
            except BlockError as exc:
                if exc.error_type not in {"fit_failed_required_story", "composition_unavailable", "fit_budget_exhausted"}:
                    raise
                if rounds >= self.policy.limits.fit_rounds_with_editor:
                    raise RunFailure("fit_unrepairable", f"the device fit failed after {rounds} editorial rounds", {"cause": exc.error_type, "details": exc.details}) from exc
                rounds += 1
                self._write("fit-repair.json", {"schema_version": 1, "round": rounds, "cause": exc.error_type, "message": str(exc), "details": exc.details})
                self.editor("fit-repair", self.run_dir, self._budget(self.policy.limits.editor_minutes))
                edition = self._read("edition.json")
                problems = validate_edition(edition)
                if problems:
                    raise RunFailure("contract_invalid", "the repaired edition fails the contract", {"problems": problems[:10]}) from exc
                # The repair edited the spec and rebuilt; carry the strikes forward by re-checking is not
                # needed: the checker's verdicts apply to sentences that still exist, so reapply them.
                verdicts = self._read("verdicts.json")
                struck = apply_verdicts(edition, verdicts, min_words=self.policy.limits.story_stands_min_words, final=True)
                self._write("edition-checked.json", struck["edition"])
                (self.run_dir / "fit-repair.json").unlink(missing_ok=True)

    def _publish(self) -> None:
        args = ["--edition", str(self.run_dir / "edition-checked.json"), "--publish-root", str(self.publish_root)]
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

    def _archive(self) -> None:
        if self.dry_run or not self.commit:
            self._phase("archive", skipped=True)
            return
        try:
            relative = self.run_dir.relative_to(self.repo)
        except ValueError:
            self._phase("archive", skipped=True, reason="run directory outside the repository")
            return
        paths = [str(relative / name) for name in SMALL_FILES if (self.run_dir / name).exists()]
        self.git("add", *paths)
        self.git("commit", "-q", "-m", f"Archive the {self.edition_id} edition")
        self._phase("archive", committed=len(paths))


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
        editor=lambda mode, run_dir, timeout: invoke_editor(mode, run_dir, timeout, config),
        checker=lambda run_dir, timeout: invoke_checker(run_dir, timeout, {**config, "checker": args.checker or config.get("checker", "claude")}),
        collect=config.get("collect_before_export", True) and not args.no_collect,
        dry_run=args.dry_run,
        commit=config.get("commit_runs", True),
    )
    return runner.run()
