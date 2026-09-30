import json
import shutil
from pathlib import Path

import pytest
import time

from conftest import BUNDLE, EDITORIAL_EXAMPLES, FIXTURES, read_json
from news_editorial.blocks import BlockError
from news_editorial.run import RunFailure, Runner, cutoff_for

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"
EDITION_ID = "2026-09-15-morning"
CUTOFF = "2026-09-15T08:00:00.000000Z"


def test_cutoff_for_converts_local_cutoff_to_utc(policy):
    assert cutoff_for("2026-09-24", policy) == "2026-09-24T03:30:00.000000Z"
    assert cutoff_for("2026-01-15", policy) == "2026-01-15T04:30:00.000000Z"


class Fakes:
    """Stand-ins for block 1, block 3, the editor session, and the checker session."""

    def __init__(self, tmp_path, strikes_first=False, editor_hangs=False, send_back_fails=False):
        self.calls = []
        self.publish_args = None
        self.device_status = "published"
        self.send_back_fails = send_back_fails
        self.omit_stories = set()
        self.checker_raises = None
        self.strikes_first = strikes_first
        self.editor_hangs = editor_hangs
        self.checker_calls = 0
        self.health_feeds = None
        self.published_ids = set()
        self.receipt_raises = None
        self.registry = tmp_path / "threads.json"
        self.publish_root = FIXTURES / "publish-root"

    def ingest(self, action, *args, timeout=0):
        self.calls.append(("ingest", action))
        if action == "export":
            output = args[args.index("--output") + 1]
            shutil.copytree(BUNDLE, output)
            return {"article_count": 254}
        if action == "health":
            if self.health_feeds is not None:
                return {"feeds": self.health_feeds}
            return {"feeds": [{"feed_id": f["feed_id"], "source": f["source"], "last_checked_at": f["last_checked_at"], "consecutive_failures": 0} for f in read_json(GOLDEN / "feeds.json")]}
        return {"status": "ok"}

    def publisher(self, action, *args, timeout=0):
        self.calls.append(("publisher", action))
        if action == "validate":
            return {"valid": True}
        if action == "publish":
            self.publish_args = list(args)
            edition = read_json(Path(args[args.index("--edition") + 1]))
            if edition["edition"]["id"] in self.published_ids and "--dry-run" not in args:
                raise BlockError("bundle_exists", "publish_news.sh publish: the edition is already stored")
            if "--dry-run" not in args:
                self.published_ids.add(edition["edition"]["id"])
            return {"status": "published", "edition_id": edition["edition"]["id"], "web_story_ids": [s["id"] for s in edition["stories"]], "device_status": self.device_status, "bundle": {"path": f"n/{EDITION_ID}/", "manifest_sha256": "sha256:" + "0" * 64}}
        if action == "receipt":
            if self.receipt_raises:
                raise self.receipt_raises
            edition_id = args[args.index("--edition") + 1]
            if edition_id not in self.published_ids:
                raise BlockError("resource_not_found", "publish_news.sh receipt: no such edition")
            return {"activated": True, "activation": {"sequence": 10}, "manifest_sha256": "sha256:" + "0" * 64, "receipt": {"web": {"story_ids": ["russian-frigate-flares-gedser"]}, "device": {"status": "published"}}}
        raise AssertionError(action)

    def editor(self, mode, run_dir, timeout):
        self.calls.append(("editor", mode))
        if self.editor_hangs:
            raise RunFailure("editor_timeout", "the editor ran past its wall clock", {"limit": "editor_minutes"})
        if self.send_back_fails and mode == "send-back":
            raise RunFailure("editor_failed", "the send-back session exited 1", {})
        if mode == "edition":
            (run_dir / "clusters.json").write_text(json.dumps({"schema_version": 1, "clusters": [
                {"id": "gedser", "event": "frigate", "members": [79, 3, 30], "confidence": 0.9, "thread": {"new": {"id": "russia-baltic", "description": "Russian pressure in the Baltic"}}}]}))
            (run_dir / "clusters-checked.json").write_text(json.dumps({"schema_version": 1, "clusters": [
                {"id": "gedser", "event": "frigate", "members": [79, 3, 30], "removed": [], "flags": [], "confidence": 0.9, "thread": {"new": {"id": "russia-baltic", "description": "Russian pressure in the Baltic"}}}], "singletons": []}))
            (run_dir / "ranking.json").write_text(json.dumps({"schema_version": 1, "candidates": [{"id": "gedser", "breadth": 7, "rank": 1}]}))
            (run_dir / "selection.json").write_text(json.dumps({"schema_version": 1, "stories": [
                {"id": "russian-frigate-flares-gedser", "cluster": "gedser", "role": "lead", "device": "required", "kicker": "Defence", "sources": [79]}], "rejected": []}))
            spec = read_json(GOLDEN / "spec.json")
            (run_dir / "spec.json").write_text(json.dumps(spec))
            (run_dir / "NOTES.md").write_text("# Editorial log\n")
        edition = read_json(GOLDEN / "edition.json")
        (run_dir / "edition.json").write_text(json.dumps(edition))
        if mode != "edition":
            with (run_dir / "NOTES.md").open("a") as handle:
                handle.write(f"\n{mode} revision.\n")
        return {"tool": "fake", "turns": 1}

    def checker(self, run_dir, timeout):
        self.checker_calls += 1
        self.calls.append(("checker", self.checker_calls))
        if self.checker_raises:
            raise self.checker_raises
        strikes = {}
        if self.strikes_first and self.checker_calls == 1:
            strikes[("russian-frigate-flares-gedser", "standard[0]", 0)] = "invented"
        check = read_json(run_dir / "check-input.json")
        stories = []
        for story in check["stories"]:
            if story["id"] in self.omit_stories:
                continue
            sentences = []
            for sentence in story["sentences"]:
                key = (story["id"], sentence["location"], sentence["sentence"])
                if key in strikes:
                    sentences.append({"location": sentence["location"], "sentence": sentence["sentence"], "verdict": "unsupported", "reason": strikes[key]})
                else:
                    sentences.append({"location": sentence["location"], "sentence": sentence["sentence"], "verdict": "supported"})
            stories.append({"id": story["id"], "sentences": sentences, "guideline_notes": []})
        (run_dir / "verdicts.json").write_text(json.dumps({"schema_version": 1, "edition_id": EDITION_ID, "stories": stories}))
        return {"tool": "fake"}


def make_runner(policy, tmp_path, fakes, **kwargs):
    run_dir = tmp_path / "runs" / EDITION_ID
    kwargs.setdefault("stray_changes", lambda: [])
    kwargs.setdefault("lock_path", tmp_path / "run.lock")
    return Runner(
        policy=policy, run_dir=run_dir, edition_id=EDITION_ID, cutoff=CUTOFF, publish_root=fakes.publish_root,
        registry=fakes.registry, ingest=fakes.ingest, publisher=fakes.publisher, collect=True, repo=tmp_path,
        **{"editor": fakes.editor, "checker": fakes.checker, "git": lambda *a: fakes.calls.append(("git", a[0])),
           "stray_changes": lambda: [], "lock_path": tmp_path / "run.lock", **kwargs},
    )


def test_happy_path_publishes_and_records(policy, tmp_path):
    fakes = Fakes(tmp_path)
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "published", status
    assert [p["name"] for p in status["phases"]] == [
        "reconcile", "collect", "window", "memory", "editor", "check", "preflight", "publish", "receipt", "threads", "deliver", "device_push", "archive"]
    assert ("publisher", "publish") in fakes.calls and ("git", "commit") in fakes.calls
    assert read_json(runner.run_dir / "status.json")["outcome"] == "published"
    assert (runner.run_dir / "check-input.json").exists()
    assert (runner.run_dir / "edition-checked.json").exists()
    registry = read_json(fakes.registry)
    thread = registry["threads"][0]
    assert thread["id"] == "russia-baltic" and thread["story_ids"] == ["russian-frigate-flares-gedser"]
    assert thread["peak_breadth"] == 7 and thread["last_edition_id"] == EDITION_ID
    assert status["published"]["edition"].endswith("edition-checked.json")


def test_send_back_revises_once_then_finalises(policy, tmp_path):
    fakes = Fakes(tmp_path, strikes_first=True)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published"
    editor_modes = [c[1] for c in fakes.calls if c[0] == "editor"]
    assert editor_modes == ["edition", "send-back"]
    assert fakes.checker_calls == 2
    check = next(p for p in status["phases"] if p["name"] == "check")
    assert check["send_back"] == ["russian-frigate-flares-gedser"] and check["rounds"] == 2


def test_rerun_reuses_verdicts_when_the_check_input_is_unchanged(policy, tmp_path):
    fakes = Fakes(tmp_path, strikes_first=True, send_back_fails=True)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "editor_failed"
    assert fakes.checker_calls == 1
    # The rerun continues from the verdicts on disk: no second checker session for the same edition.
    fakes.send_back_fails = False
    fakes.calls.clear()
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published", status["failure"]
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["send-back"]
    assert fakes.checker_calls == 2
    check = next(p for p in status["phases"] if p["name"] == "check")
    assert check["rounds"] == 2 and check["resumed"] is True
    assert next(p for p in status["phases"] if p["name"] == "editor")["resumed"] is True


def test_the_run_publishes_web_only_without_a_fit_phase(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published"
    assert "fit" not in [p["name"] for p in status["phases"]]
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["edition"]
    assert fakes.publish_args is not None and "--skip-device" in fakes.publish_args
    assert not any(c == ("publisher", "fit") for c in fakes.calls)


def test_editor_timeout_fails_loudly_without_publishing(policy, tmp_path):
    fakes = Fakes(tmp_path, editor_hangs=True)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "editor_timeout"
    assert status["failure"]["phase"] == "editor"
    assert ("publisher", "publish") not in fakes.calls
    assert read_json(tmp_path / "runs" / EDITION_ID / "status.json")["outcome"] == "failed"


def test_dry_run_neither_commits_nor_advances_threads(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes, dry_run=True).run()
    assert status["outcome"] == "dry_run"
    assert ("git", "commit") not in fakes.calls and not fakes.registry.exists()
    assert ("publisher", "publish") in fakes.calls


def test_published_run_is_not_rerun(policy, tmp_path):
    fakes = Fakes(tmp_path)
    make_runner(policy, tmp_path, fakes).run()
    with pytest.raises(RunFailure) as info:
        make_runner(policy, tmp_path, Fakes(tmp_path)).run()
    assert info.value.error_type == "conflict"


def test_incomplete_verdicts_fail_the_run(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.omit_stories = {"russian-frigate-flares-gedser"}
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "failed"
    assert status["failure"]["type"] == "verdicts_invalid"
    assert "russian-frigate-flares-gedser" in json.dumps(status["failure"]["details"])
    assert ("publisher", "publish") not in fakes.calls


def test_a_session_writing_outside_the_run_directory_stops_the_run(policy, tmp_path):
    fakes = Fakes(tmp_path)
    tree = ["ingest/README.md"]  # the owner's own work in progress, there before the run
    original_editor = fakes.editor

    def editor(mode, run_dir, timeout):
        tree.extend(["editorial/policy.yaml", f"runs/{EDITION_ID}/spec.json"])
        return original_editor(mode, run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: list(tree)).run()
    assert status["outcome"] == "failed"
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["phase"] == "editor"
    assert status["failure"]["details"]["paths"] == ["editorial/policy.yaml"]
    assert fakes.checker_calls == 0
    assert ("publisher", "publish") not in fakes.calls


def test_a_checker_writing_outside_the_run_directory_stops_the_run(policy, tmp_path):
    fakes = Fakes(tmp_path)
    tree: list[str] = []
    original_checker = fakes.checker

    def checker(run_dir, timeout):
        tree.append("publisher/src/publish/web.ts")
        return original_checker(run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, checker=checker, stray_changes=lambda: list(tree)).run()
    assert status["outcome"] == "failed"
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["phase"] == "check"
    assert ("publisher", "publish") not in fakes.calls


def test_the_owners_work_in_progress_does_not_block_the_paper(policy, tmp_path):
    fakes = Fakes(tmp_path)
    dirty = ["ingest/README.md", "ingest/migrations/005_sighting_content.sql", "editorial/config/launchd/ai.copenhagen-daily.edition.plist"]
    status = make_runner(policy, tmp_path, fakes, stray_changes=lambda: list(dirty)).run()
    assert status["outcome"] == "published", status
    assert ("publisher", "publish") in fakes.calls


def test_an_unexpected_exception_is_recorded_in_status(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.checker_raises = KeyError("stories")
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "failed"
    assert status["failure"]["phase"] == "check" and status["failure"]["type"] == "internal_error"
    assert "KeyError" in status["failure"]["message"]
    assert read_json(runner.run_dir / "status.json")["outcome"] == "failed"


def test_a_second_run_finds_the_lock_busy(policy, tmp_path):
    import fcntl

    fakes = Fakes(tmp_path)
    lock = tmp_path / "run.lock"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = make_runner(policy, tmp_path, fakes, lock_path=lock).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "lock_busy"
    assert fakes.calls == []


def test_failure_notifies(policy, tmp_path):
    fakes = Fakes(tmp_path, editor_hangs=True)
    notes = []
    runner = make_runner(policy, tmp_path, fakes, notifier=lambda subject, body: notes.append((subject, body)))
    status = runner.run()
    assert status["outcome"] == "failed"
    assert len(notes) == 1 and "editor_timeout" in notes[0][1] and EDITION_ID in notes[0][0]


def test_success_does_not_notify(policy, tmp_path):
    fakes = Fakes(tmp_path)
    notes = []
    make_runner(policy, tmp_path, fakes, notifier=lambda s, b: notes.append(s)).run()
    assert notes == []


def test_delivery_syncs_the_live_site_after_activation(policy, tmp_path):
    fakes = Fakes(tmp_path)
    delivered = []
    runner = make_runner(policy, tmp_path, fakes, deliverer=lambda root: delivered.append(root) or {"synced": True})
    status = runner.run()
    assert status["outcome"] == "published"
    assert delivered == [fakes.publish_root]
    names = [p["name"] for p in status["phases"]]
    assert names.index("deliver") > names.index("threads") and names.index("deliver") < names.index("archive")


def test_delivery_is_skipped_on_a_dry_run(policy, tmp_path):
    fakes = Fakes(tmp_path)
    delivered = []
    status = make_runner(policy, tmp_path, fakes, deliverer=lambda root: delivered.append(root), dry_run=True).run()
    assert delivered == [] and next(p for p in status["phases"] if p["name"] == "deliver")["skipped"] is True


def test_retry_skips_an_edition_that_already_succeeded(policy, tmp_path):
    fakes = Fakes(tmp_path)
    make_runner(policy, tmp_path, fakes, dry_run=True).run()
    again = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, again, retry=True).run()
    assert status["outcome"] == "skipped"
    assert ("editor", "edition") not in again.calls


def test_retry_resumes_a_failed_edition(policy, tmp_path):
    fakes = Fakes(tmp_path, editor_hangs=True)
    make_runner(policy, tmp_path, fakes).run()
    again = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, again, retry=True).run()
    assert status["outcome"] == "published"


def test_archive_commits_the_final_status(policy, tmp_path):
    fakes = Fakes(tmp_path)
    committed = {}

    def git(*args):
        fakes.calls.append(("git", args[0]))
        if args[0] == "commit":
            committed["status"] = (tmp_path / "runs" / EDITION_ID / "status.json").read_text()

    runner = make_runner(policy, tmp_path, fakes, git=git)
    runner.run()
    final = (tmp_path / "runs" / EDITION_ID / "status.json").read_text()
    assert committed["status"] == final
    assert json.loads(final)["outcome"] == "published"


def test_collect_waits_for_the_lock_then_proceeds(policy, tmp_path):
    fakes = Fakes(tmp_path)
    attempts = []
    real_ingest = fakes.ingest

    def busy_then_free(action, *args, timeout=0):
        if action == "collect":
            attempts.append(1)
            if len(attempts) < 3:
                raise BlockError("lock_busy", "Another writer holds the process lock.")
        return real_ingest(action, *args, timeout=timeout)

    fakes.ingest = busy_then_free
    runner = make_runner(policy, tmp_path, fakes, collect_wait_seconds=0)
    status = runner.run()
    assert status["outcome"] == "published", status["failure"]
    assert len(attempts) == 3
    assert next(p for p in status["phases"] if p["name"] == "collect")["waited_attempts"] == 2


def test_collect_gives_up_on_a_held_lock_and_uses_the_last_poll(policy, tmp_path):
    fakes = Fakes(tmp_path)
    real_ingest = fakes.ingest

    def always_busy(action, *args, timeout=0):
        if action == "collect":
            raise BlockError("lock_busy", "Another writer holds the process lock.")
        return real_ingest(action, *args, timeout=timeout)

    fakes.ingest = always_busy
    runner = make_runner(policy, tmp_path, fakes, collect_wait_seconds=0, collect_max_attempts=3)
    status = runner.run()
    assert status["outcome"] == "published", status["failure"]
    collect = next(p for p in status["phases"] if p["name"] == "collect")
    assert collect["skipped"] is True and collect["reason"] == "lock_busy"


def test_collect_is_skipped_when_the_collector_polled_recently(policy, tmp_path):
    fakes = Fakes(tmp_path)
    real_ingest = fakes.ingest
    calls = []

    def ingest(action, *args, timeout=0):
        calls.append(action)
        if action == "health":
            result = real_ingest(action, *args, timeout=timeout)
            for feed in result["feeds"]:
                feed["last_successful_poll_at"] = "2026-09-15T07:55:00.000000Z"
            return result
        return real_ingest(action, *args, timeout=timeout)

    fakes.ingest = ingest
    runner = make_runner(policy, tmp_path, fakes, now=lambda: "2026-09-15T08:05:00.000000Z", collect_max_age_minutes=20)
    status = runner.run()
    assert status["outcome"] == "published", status["failure"]
    collect = next(p for p in status["phases"] if p["name"] == "collect")
    assert collect["skipped"] is True and collect["reason"] == "recent_poll"
    assert "collect" not in calls


def test_collect_runs_when_the_last_poll_is_old(policy, tmp_path):
    fakes = Fakes(tmp_path)
    real_ingest = fakes.ingest
    calls = []

    def ingest(action, *args, timeout=0):
        calls.append(action)
        if action == "health":
            result = real_ingest(action, *args, timeout=timeout)
            for feed in result["feeds"]:
                feed["last_successful_poll_at"] = "2026-09-15T06:00:00.000000Z"
            return result
        return real_ingest(action, *args, timeout=timeout)

    fakes.ingest = ingest
    runner = make_runner(policy, tmp_path, fakes, now=lambda: "2026-09-15T08:05:00.000000Z", collect_max_age_minutes=20)
    status = runner.run()
    assert status["outcome"] == "published", status["failure"]
    assert "collect" in calls


def test_the_device_page_is_rendered_only_when_the_desk_config_asks(policy, tmp_path):
    fakes = Fakes(tmp_path)
    make_runner(policy, tmp_path, fakes, device=True).run()
    assert "--skip-device" not in fakes.publish_args
    fakes = Fakes(tmp_path / "again")
    make_runner(policy, tmp_path / "again", fakes).run()
    assert "--skip-device" in fakes.publish_args


def test_the_device_page_is_pushed_after_delivery_and_a_push_failure_does_not_fail_the_edition(policy, tmp_path):
    fakes = Fakes(tmp_path)
    pushed = []
    runner = make_runner(policy, tmp_path, fakes, device=True, device_pusher=lambda root: pushed.append(root) or {"pushed": True, "to": "host:/x.png"})
    status = runner.run()
    assert status["outcome"] == "published"
    names = [p["name"] for p in status["phases"]]
    assert names.index("device_push") == names.index("deliver") + 1
    assert pushed == [fakes.publish_root]

    def broken(root):
        raise RuntimeError("scp: connection refused")

    fakes = Fakes(tmp_path / "broken")
    notes = []
    runner = make_runner(policy, tmp_path / "broken", fakes, device=True, device_pusher=broken, notifier=lambda s, b: notes.append(s))
    status = runner.run()
    assert status["outcome"] == "published"
    phase = next(p for p in status["phases"] if p["name"] == "device_push")
    assert phase["failed"] and "connection refused" in phase["error"]
    assert any("device" in n.lower() for n in notes)


def test_the_device_push_is_skipped_when_no_device_page_was_published(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.device_status = "failed"
    pushed = []
    status = make_runner(policy, tmp_path, fakes, device=True, device_pusher=lambda root: pushed.append(root)).run()
    assert status["outcome"] == "published" and pushed == []
    assert next(p for p in status["phases"] if p["name"] == "device_push")["skipped"]


# ---- block 2 review, 30 September: the trust boundary and the retry paths ----------------------------


def test_a_session_that_rewrites_the_evidence_stops_the_run_before_the_check(policy, tmp_path):
    fakes = Fakes(tmp_path)
    original_editor = fakes.editor

    def editor(mode, run_dir, timeout):
        window = json.loads((run_dir / "window.json").read_text())
        for article in window["articles"]:
            article["description"] = "INVENTED"
        (run_dir / "window.json").write_text(json.dumps(window))
        return original_editor(mode, run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, editor=editor).run()
    assert status["outcome"] == "failed"
    assert status["failure"]["type"] == "input_modified"
    assert "window.json" in json.dumps(status["failure"]["details"])
    assert fakes.checker_calls == 0


def test_a_session_that_overwrites_the_owners_dirty_file_is_caught_by_content(policy, tmp_path):
    fakes = Fakes(tmp_path)
    dirty = tmp_path / "ingest" / "README.md"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("the owner's half-finished sentence")
    original_editor = fakes.editor

    def editor(mode, run_dir, timeout):
        dirty.write_text("rewritten by the session")
        return original_editor(mode, run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: ["ingest/README.md"]).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "stray_edits"
    assert status["failure"]["details"]["paths"] == ["ingest/README.md"]


def test_a_stray_edit_is_reported_even_when_the_session_itself_fails(policy, tmp_path):
    fakes = Fakes(tmp_path)
    tree = []

    def editor(mode, run_dir, timeout):
        tree.append("editorial/policy.yaml")
        raise RunFailure("editor_timeout", "the editor ran past its wall clock", {"limit": "editor_minutes"})

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: list(tree)).run()
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["details"]["after"] == "editor_timeout"


def test_the_archive_commit_leaves_unrelated_staged_work_alone(policy, tmp_path):
    import subprocess

    git = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True)  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("seed")
    git("add", "seed.txt")
    git("commit", "-q", "-m", "seed")
    (tmp_path / "unrelated.txt").write_text("the owner staged this before the run")
    git("add", "unrelated.txt")
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes, git=lambda *a: git(*a), commit=True).run()
    assert status["outcome"] == "published", status
    shown = git("show", "--stat", "--name-only", "--format=", "HEAD").stdout
    assert "unrelated.txt" not in shown and f"runs/{EDITION_ID}/status.json" in shown
    assert "unrelated.txt" in git("diff", "--cached", "--name-only").stdout


def test_invalid_cached_verdicts_are_not_reused_on_retry(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.omit_stories = {"russian-frigate-flares-gedser"}
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["failure"]["type"] == "verdicts_invalid"
    fakes.omit_stories = set()
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published", status["failure"]
    assert fakes.checker_calls == 2


def test_an_invalid_edition_on_disk_is_set_aside_and_the_editor_runs_again(policy, tmp_path):
    fakes = Fakes(tmp_path)
    run_dir = tmp_path / "runs" / EDITION_ID
    run_dir.mkdir(parents=True)
    (run_dir / "edition.json").write_text('{"schema_version": 1, "edition": {"id": "x"}, "stories": []}')
    (run_dir / "NOTES.md").write_text("# half\n")
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published", status["failure"]
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["edition"]
    assert list(run_dir.glob("edition.invalid-*.json"))


def test_a_timed_out_session_takes_its_children_with_it(tmp_path):
    from news_editorial.run import _headless

    marker = tmp_path / "marker"
    script = tmp_path / "parent.sh"
    script.write_text(f'#!/bin/sh\n(sleep 1; touch "{marker}") &\nsleep 5\n')
    script.chmod(0o755)
    with pytest.raises(RunFailure) as failure:
        _headless([str(script)], tmp_path, 0.3, "editor-edition", tmp_path, "editor_minutes")
    assert failure.value.error_type == "editor_minutes_timeout"
    time.sleep(1.5)
    assert not marker.exists(), "the session's child kept running after the timeout"


def test_a_send_back_may_not_change_the_edition_id_or_unnamed_stories(policy, tmp_path):
    fakes = Fakes(tmp_path, strikes_first=True)
    original_editor = fakes.editor

    def renaming_editor(mode, run_dir, timeout):
        record = original_editor(mode, run_dir, timeout)
        if mode == "send-back":
            edition = json.loads((run_dir / "edition.json").read_text())
            edition["edition"]["id"] = "2026-09-15-evening"
            (run_dir / "edition.json").write_text(json.dumps(edition))
        return record

    status = make_runner(policy, tmp_path, fakes, editor=renaming_editor).run()
    assert status["failure"]["type"] == "conflict" and ("publisher", "publish") not in fakes.calls

    fakes = Fakes(tmp_path / "b", strikes_first=True)
    original_editor = fakes.editor

    def overreaching_editor(mode, run_dir, timeout):
        record = original_editor(mode, run_dir, timeout)
        if mode == "send-back":
            edition = json.loads((run_dir / "edition.json").read_text())
            other = next(s for s in edition["stories"] if s["id"] != "russian-frigate-flares-gedser")
            other["copy"]["headline"] = "A headline nobody sent back"
            (run_dir / "edition.json").write_text(json.dumps(edition))
        return record

    status = make_runner(policy, tmp_path / "b", fakes, editor=overreaching_editor).run()
    assert status["failure"]["type"] == "send_back_overreach"
    assert other_id_in(status["failure"]["details"])


def other_id_in(details):
    return any(sid != "russian-frigate-flares-gedser" for sid in details.get("changed", []))


def test_collect_runs_when_any_healthy_feed_is_stale(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.health_feeds = [
        {"feed_id": "fresh", "source": "dr", "last_successful_poll_at": "2026-09-15T07:55:00.000000Z", "last_checked_at": "2026-09-15T07:55:00.000000Z", "consecutive_failures": 0},
        {"feed_id": "stale", "source": "tv2", "last_successful_poll_at": "2026-09-01T07:55:00.000000Z", "last_checked_at": "2026-09-01T07:55:00.000000Z", "consecutive_failures": 0},
    ]
    status = make_runner(policy, tmp_path, fakes, now=lambda: "2026-09-15T08:00:00.000000Z").run()
    collect = next(p for p in status["phases"] if p["name"] == "collect")
    assert not collect.get("skipped"), collect
    fakes = Fakes(tmp_path / "b")
    fakes.health_feeds = [
        {"feed_id": "fresh", "source": "dr", "last_successful_poll_at": "2026-09-15T07:55:00.000000Z", "last_checked_at": "2026-09-15T07:55:00.000000Z", "consecutive_failures": 0},
        {"feed_id": "broken", "source": "tv2", "last_successful_poll_at": "2026-09-01T07:55:00.000000Z", "last_checked_at": "2026-09-15T07:55:00.000000Z", "consecutive_failures": 3},
    ]
    status = make_runner(policy, tmp_path / "b", fakes, now=lambda: "2026-09-15T08:00:00.000000Z").run()
    collect = next(p for p in status["phases"] if p["name"] == "collect")
    assert collect.get("skipped") and collect["reason"] == "recent_poll"



def test_a_failure_after_activation_resumes_the_rest_without_republishing(policy, tmp_path):
    fakes = Fakes(tmp_path)
    notes = []

    def broken(root):
        raise RuntimeError("network down")

    status = make_runner(policy, tmp_path, fakes, deliverer=broken, notifier=lambda s, b: notes.append(b)).run()
    assert status["outcome"] == "failed" and status["failure"]["phase"] == "deliver"
    assert status["published"]["status"] == "published"
    assert "activated" in notes[-1] and "resume" in notes[-1]
    assert [c for c in fakes.calls if c == ("publisher", "publish")] == [("publisher", "publish")]

    delivered = []
    fakes.calls.clear()
    status = make_runner(policy, tmp_path, fakes, deliverer=lambda root: delivered.append(root) or {"synced": True}, retry=True).run()
    assert status["outcome"] == "published", status["failure"]
    assert ("publisher", "publish") not in fakes.calls and ("editor", "edition") not in fakes.calls
    assert delivered == [fakes.publish_root]
    reconcile = next(p for p in status["phases"] if p["name"] == "reconcile")
    assert reconcile["activated"] is True
    assert next(p for p in status["phases"] if p["name"] == "publish")["skipped"]
    assert [f["phase"] for f in status["previous_failures"]] == ["deliver"]
    assert ("git", "commit") in fakes.calls


def test_a_store_that_needs_recovery_stops_the_run_before_any_session(policy, tmp_path):
    fakes = Fakes(tmp_path)
    fakes.receipt_raises = BlockError("recovery_required", "publish_news.sh receipt: a publication is pending; run recover")
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "recovery_required"
    assert ("editor", "edition") not in fakes.calls and ("ingest", "collect") not in fakes.calls
