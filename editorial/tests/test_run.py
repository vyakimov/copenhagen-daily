import json
import shutil
from pathlib import Path

import pytest

from conftest import BUNDLE, EDITORIAL_EXAMPLES, FIXTURES, read_json
from news_editorial.run import RunFailure, Runner, cutoff_for

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"
EDITION_ID = "2026-09-15-morning"
CUTOFF = "2026-09-15T08:00:00.000000Z"


def test_cutoff_for_converts_local_cutoff_to_utc(policy):
    assert cutoff_for("2026-09-24", policy) == "2026-09-24T06:00:00.000000Z"
    assert cutoff_for("2026-01-15", policy) == "2026-01-15T07:00:00.000000Z"


class Fakes:
    """Stand-ins for block 1, block 3, the editor session, and the checker session."""

    def __init__(self, tmp_path, strikes_first=False, editor_hangs=False, send_back_fails=False):
        self.calls = []
        self.publish_args = None
        self.send_back_fails = send_back_fails
        self.omit_stories = set()
        self.checker_raises = None
        self.strikes_first = strikes_first
        self.editor_hangs = editor_hangs
        self.checker_calls = 0
        self.registry = tmp_path / "threads.json"
        self.publish_root = FIXTURES / "publish-root"

    def ingest(self, action, *args, timeout=0):
        self.calls.append(("ingest", action))
        if action == "export":
            output = args[args.index("--output") + 1]
            shutil.copytree(BUNDLE, output)
            return {"article_count": 254}
        if action == "health":
            return {"feeds": [{"feed_id": f["feed_id"], "source": f["source"], "last_checked_at": f["last_checked_at"], "consecutive_failures": 0} for f in read_json(GOLDEN / "feeds.json")]}
        return {"status": "ok"}

    def publisher(self, action, *args, timeout=0):
        self.calls.append(("publisher", action))
        if action == "validate":
            return {"valid": True}
        if action == "publish":
            self.publish_args = list(args)
            edition = read_json(Path(args[args.index("--edition") + 1]))
            return {"status": "published", "edition_id": edition["edition"]["id"], "web_story_ids": [s["id"] for s in edition["stories"]], "device_status": "published", "bundle": {"path": f"n/{EDITION_ID}/", "manifest_sha256": "sha256:" + "0" * 64}}
        if action == "receipt":
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
        registry=fakes.registry, ingest=fakes.ingest, publisher=fakes.publisher, editor=fakes.editor, checker=fakes.checker,
        git=lambda *a: fakes.calls.append(("git", a[0])), collect=True, repo=tmp_path,
        **{"stray_changes": lambda: [], "lock_path": tmp_path / "run.lock", **kwargs},
    )


def test_happy_path_publishes_and_records(policy, tmp_path):
    fakes = Fakes(tmp_path)
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "published", status
    assert [p["name"] for p in status["phases"]] == [
        "collect", "window", "memory", "editor", "check", "preflight", "publish", "receipt", "threads", "deliver", "archive"]
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


def test_stray_edits_outside_the_run_directory_stop_the_publish(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes, stray_changes=lambda: ["editorial/policy.yaml", f"runs/{EDITION_ID}/spec.json"]).run()
    assert status["outcome"] == "failed"
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["details"]["paths"] == ["editorial/policy.yaml"]
    assert ("publisher", "publish") not in fakes.calls


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
