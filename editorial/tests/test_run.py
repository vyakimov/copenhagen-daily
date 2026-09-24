import json
import shutil
from pathlib import Path

import pytest

from conftest import BUNDLE, EDITORIAL_EXAMPLES, FIXTURES, read_json
from news_editorial.run import RunFailure, Runner, cutoff_for
from news_editorial.blocks import BlockError

GOLDEN = EDITORIAL_EXAMPLES / "2026-09-15-morning"
EDITION_ID = "2026-09-15-morning"
CUTOFF = "2026-09-15T08:00:00.000000Z"


def test_cutoff_for_converts_local_cutoff_to_utc(policy):
    assert cutoff_for("2026-09-24", policy) == "2026-09-24T06:00:00.000000Z"
    assert cutoff_for("2026-01-15", policy) == "2026-01-15T07:00:00.000000Z"


class Fakes:
    """Stand-ins for block 1, block 3, the editor session, and the checker session."""

    def __init__(self, tmp_path, strikes_first=False, fit_failures=0, editor_hangs=False):
        self.calls = []
        self.strikes_first = strikes_first
        self.fit_failures = fit_failures
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
        if action == "fit":
            if self.fit_failures:
                self.fit_failures -= 1
                raise BlockError("fit_failed_required_story", "a required story cannot be placed", {"story_id": "x", "fit_report": {"status": "failed"}})
            return {"status": "fit", "composition": "lead-wide", "fit_report": {"status": "fit"}}
        if action == "validate":
            return {"valid": True}
        if action == "publish":
            edition = read_json(Path(args[args.index("--edition") + 1]))
            return {"status": "published", "edition_id": edition["edition"]["id"], "web_story_ids": [s["id"] for s in edition["stories"]], "device_status": "published", "bundle": {"path": f"n/{EDITION_ID}/", "manifest_sha256": "sha256:" + "0" * 64}}
        if action == "receipt":
            return {"activated": True, "activation": {"sequence": 10}, "manifest_sha256": "sha256:" + "0" * 64, "receipt": {"web": {"story_ids": ["russian-frigate-flares-gedser"]}, "device": {"status": "published"}}}
        raise AssertionError(action)

    def editor(self, mode, run_dir, timeout):
        self.calls.append(("editor", mode))
        if self.editor_hangs:
            raise RunFailure("editor_timeout", "the editor ran past its wall clock", {"limit": "editor_minutes"})
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
        strikes = []
        if self.strikes_first and self.checker_calls == 1:
            strikes = [{"location": "standard[0]", "sentence": 0, "verdict": "unsupported", "reason": "invented"}]
        (run_dir / "verdicts.json").write_text(json.dumps({"schema_version": 1, "edition_id": EDITION_ID, "stories": [
            {"id": "russian-frigate-flares-gedser", "sentences": strikes, "guideline_notes": []}]}))
        return {"tool": "fake"}


def make_runner(policy, tmp_path, fakes, **kwargs):
    run_dir = tmp_path / "runs" / EDITION_ID
    return Runner(
        policy=policy, run_dir=run_dir, edition_id=EDITION_ID, cutoff=CUTOFF, publish_root=fakes.publish_root,
        registry=fakes.registry, ingest=fakes.ingest, publisher=fakes.publisher, editor=fakes.editor, checker=fakes.checker,
        git=lambda *a: fakes.calls.append(("git", a[0])), collect=True, repo=tmp_path, **kwargs,
    )


def test_happy_path_publishes_and_records(policy, tmp_path):
    fakes = Fakes(tmp_path)
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "published", status
    assert [p["name"] for p in status["phases"]] == [
        "collect", "window", "memory", "editor", "check", "preflight", "fit", "publish", "receipt", "threads", "archive"]
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


def test_fit_repair_is_bounded(policy, tmp_path):
    fakes = Fakes(tmp_path, fit_failures=1)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published"
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["edition", "fit-repair"]
    fakes = Fakes(tmp_path / "b", fit_failures=99)
    (tmp_path / "b").mkdir()
    status = make_runner(policy, tmp_path / "b", fakes).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "fit_unrepairable"
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["edition"] + ["fit-repair"] * policy.limits.fit_rounds_with_editor
    assert ("publisher", "publish") not in fakes.calls


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
