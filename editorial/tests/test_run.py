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
        self.writer_modes = []
        self.revised_headline = None
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
        """The desk session: clusters, ranking, the selection and the log. No copy."""
        self.calls.append(("editor", mode))
        if self.editor_hangs:
            raise RunFailure("editor_timeout", "the editor ran past its wall clock", {"limit": "editor_minutes"})
        assert mode == "desk", mode
        (run_dir / "clusters.json").write_text(json.dumps({"schema_version": 1, "clusters": [
            {"id": "gedser", "event": "frigate", "members": [79, 3, 30], "confidence": 0.9, "thread": {"new": {"id": "russia-baltic", "description": "Russian pressure in the Baltic"}}}]}))
        (run_dir / "clusters-checked.json").write_text(json.dumps({"schema_version": 1, "clusters": [
            {"id": "gedser", "event": "frigate", "members": [79, 3, 30], "removed": [], "flags": [], "confidence": 0.9, "thread": {"new": {"id": "russia-baltic", "description": "Russian pressure in the Baltic"}}}], "singletons": []}))
        (run_dir / "ranking.json").write_text(json.dumps({"schema_version": 1, "candidates": [{"id": "gedser", "breadth": 7, "rank": 1}]}))
        spec = read_json(GOLDEN / "spec.json")
        stories = [{"id": s["id"], "cluster": "gedser" if s["role"] == "lead" else None, "role": s["role"], "kicker": s["kicker"], "sources": s["sources"]} for s in spec["stories"]]
        (run_dir / "selection.json").write_text(json.dumps({
            "schema_version": 1, "edition": {"presentation": spec["edition"]["presentation"], "note": spec["edition"]["note"]},
            "stories": stories, "rejected": []}))
        (run_dir / "NOTES.md").write_text("# Editorial log\n")
        return {"tool": "fake", "turns": 1}

    def writer(self, brief_path, timeout):
        """One story's session: answers with the golden copy for that story."""
        brief = read_json(brief_path)
        self.writer_modes.append((brief["story"]["id"], brief["mode"]))
        if self.send_back_fails and brief["mode"] == "revise":
            raise RunFailure("writer_failed", "the revising session exited 1", {})
        spec = read_json(GOLDEN / "spec.json")
        story = next(s for s in spec["stories"] if s["id"] == brief["story"]["id"])
        copy = {k: v for k, v in story.items() if k in ("headline", "headline_short", "deck", "lede", "extended", "standard", "short", "callouts")}
        if brief["mode"] == "revise" and self.revised_headline:
            copy["headline"] = self.revised_headline
        return {"tool": "fake", "result": json.dumps(copy), "total_cost_usd": 0.1}

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
        **{"editor": fakes.editor, "writer": fakes.writer, "checker": fakes.checker, "git": lambda *a: fakes.calls.append(("git", a[0])),
           "stray_changes": lambda: [], "lock_path": tmp_path / "run.lock", **kwargs},
    )


def test_happy_path_publishes_and_records(policy, tmp_path):
    fakes = Fakes(tmp_path)
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "published", status
    assert [p["name"] for p in status["phases"]] == [
        "reconcile", "inputs", "collect", "window", "memory", "editor", "write", "check", "preflight", "publish", "receipt", "threads", "deliver", "device_push", "archive"]
    write = next(p for p in status["phases"] if p["name"] == "write")
    assert write["stories"] == len(read_json(GOLDEN / "spec.json")["stories"]) and write["sessions"] == write["stories"]
    assert (runner.run_dir / "stories" / "russian-frigate-flares-gedser" / "brief.json").exists()
    brief = read_json(runner.run_dir / "stories" / "russian-frigate-flares-gedser" / "brief.json")
    assert brief["story"]["role"] == "lead" and brief["example"]["role"] == "lead" and "id" not in brief["example"]
    assert "Every sentence should carry a new fact" in brief["guidelines"] and brief["style"].startswith("#") and "story writer" in brief["skill"]
    assert all(a["source"] in {"dr", "kristeligt_dagblad", "politiken", "berlingske", "jp", "bbc", "guardian", "nytimes", "ft", "wsj", "wapo", "tv2", "borsen", "altinget", "information", "via_ritzau", "economist"} for a in brief["articles"])
    assert read_json(runner.run_dir / "spec.json")["edition"]["id"] == EDITION_ID
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
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["desk"]
    assert [m for m in fakes.writer_modes if m[1] == "revise"] == [("russian-frigate-flares-gedser", "revise")]
    assert fakes.checker_calls == 2
    check = next(p for p in status["phases"] if p["name"] == "check")
    assert check["send_back"] == ["russian-frigate-flares-gedser"] and check["rounds"] == 2


def test_rerun_reuses_verdicts_when_the_check_input_is_unchanged(policy, tmp_path):
    fakes = Fakes(tmp_path, strikes_first=True, send_back_fails=True)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "writer_failed"
    assert fakes.checker_calls == 1
    # The rerun continues from the verdicts on disk: no second checker session for the same edition.
    fakes.send_back_fails = False
    fakes.calls.clear()
    fakes.writer_modes.clear()
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published", status["failure"]
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == []
    assert fakes.writer_modes == [("russian-frigate-flares-gedser", "revise")]
    assert fakes.checker_calls == 2
    check = next(p for p in status["phases"] if p["name"] == "check")
    assert check["rounds"] == 2 and check["resumed"] is True
    assert next(p for p in status["phases"] if p["name"] == "editor")["resumed"] is True
    assert next(p for p in status["phases"] if p["name"] == "write")["resumed"] is True


def test_the_run_publishes_web_only_without_a_fit_phase(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published"
    assert "fit" not in [p["name"] for p in status["phases"]]
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["desk"]
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
    assert [c[1] for c in fakes.calls if c[0] == "editor"] == ["desk"]
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


def test_a_send_back_rewrites_only_the_stories_sent_back(policy, tmp_path):
    fakes = Fakes(tmp_path, strikes_first=True)
    fakes.revised_headline = "Frigate fires flares; a shorter account"
    runner = make_runner(policy, tmp_path, fakes)
    status = runner.run()
    assert status["outcome"] == "published", status["failure"]
    assert fakes.writer_modes.count(("russian-frigate-flares-gedser", "revise")) == 1
    assert len([m for m in fakes.writer_modes if m[1] == "revise"]) == 1
    brief = read_json(runner.run_dir / "stories" / "russian-frigate-flares-gedser" / "brief.json")
    assert brief["mode"] == "revise" and brief["strikes"][0]["location"] == "standard[0]" and brief["strikes"][0]["reason"] == "invented"
    assert brief["previous"]["headline"] != fakes.revised_headline
    checked = read_json(runner.run_dir / "edition-checked.json")
    lead = next(s for s in checked["stories"] if s["id"] == "russian-frigate-flares-gedser")
    assert lead["copy"]["headline"] == fakes.revised_headline
    golden = {s["id"]: s for s in read_json(GOLDEN / "spec.json")["stories"]}
    for story in checked["stories"]:
        if story["id"] != lead["id"]:
            assert story["copy"]["headline"] == golden[story["id"]]["headline"]


def test_an_incomplete_selection_stops_the_run_before_any_writing(policy, tmp_path):
    fakes = Fakes(tmp_path)
    original = fakes.editor

    def no_lead(mode, run_dir, timeout):
        record = original(mode, run_dir, timeout)
        selection = read_json(run_dir / "selection.json")
        selection["stories"] = [s for s in selection["stories"] if s["role"] != "lead"]
        (run_dir / "selection.json").write_text(json.dumps(selection))
        return record

    status = make_runner(policy, tmp_path, fakes, editor=no_lead).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "selection_invalid"
    assert status["failure"]["phase"] == "editor" and fakes.writer_modes == []


def test_a_writer_that_answers_badly_is_asked_once_more_then_fails_the_run(policy, tmp_path):
    fakes = Fakes(tmp_path)
    answers = []

    def babbling_writer(brief_path, timeout):
        brief = read_json(brief_path)
        answers.append(brief.get("previous_answer_problems"))
        if brief["story"]["role"] == "lead":
            return {"result": "I could not write this.", "total_cost_usd": 0}
        return fakes.writer(brief_path, timeout)

    status = make_runner(policy, tmp_path, fakes, writer=babbling_writer).run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "writer_failed"
    assert status["failure"]["phase"] == "write" and "russian-frigate-flares-gedser" in status["failure"]["message"]
    assert any(a for a in answers if a), "the second attempt carries the first answer's problem"


def test_a_writer_retry_does_not_move_the_evidence_baseline(policy, tmp_path):
    """Review finding: a retry re-recorded every input, so evidence changed during the write phase
    became the new baseline. Only the retry brief itself may join the record."""
    fakes = Fakes(tmp_path)
    attempts = []

    def poisoning_writer(brief_path, timeout):
        brief = read_json(brief_path)
        if brief["story"]["role"] == "lead":
            attempts.append(brief_path.name)
            if len(attempts) == 1:
                run_dir = brief_path.parents[2]
                (run_dir / "window.md").write_text("POISONED\n")
                return {"result": "not json", "total_cost_usd": 0}
        return fakes.writer(brief_path, timeout)

    status = make_runner(policy, tmp_path, fakes, writer=poisoning_writer).run()
    assert attempts == ["brief.json", "brief-retry.json"]
    assert status["outcome"] == "failed" and status["failure"]["type"] == "input_modified", status["failure"]
    assert "window.md" in status["failure"]["details"]["paths"]


def test_writers_stop_when_the_run_has_no_wall_clock_left(policy, tmp_path):
    fakes = Fakes(tmp_path)
    holder = {}

    def exhausting_editor(mode, run_dir, timeout):
        record = fakes.editor(mode, run_dir, timeout)
        holder["runner"].started -= policy.limits.run_minutes * 60 + 1
        return record

    runner = make_runner(policy, tmp_path, fakes, editor=exhausting_editor)
    holder["runner"] = runner
    status = runner.run()
    assert status["outcome"] == "failed" and status["failure"]["type"] == "run_timeout"
    assert status["failure"]["phase"] == "write" and fakes.writer_modes == []


def test_a_broken_cached_story_is_set_aside_and_written_again(policy, tmp_path):
    fakes = Fakes(tmp_path)
    run_dir = tmp_path / "runs" / EDITION_ID
    story_dir = run_dir / "stories" / "russian-frigate-flares-gedser"
    story_dir.mkdir(parents=True)
    (story_dir / "story.json").write_text("{")
    (story_dir / "brief.json").write_text("{}")
    status = make_runner(policy, tmp_path, fakes).run()
    assert status["outcome"] == "published", status["failure"]
    assert ("russian-frigate-flares-gedser", "write") in fakes.writer_modes
    assert list(story_dir.glob("story.invalid-*.json"))


def test_a_cached_story_is_reused_only_with_the_brief_that_produced_it(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes, dry_run=True).run()
    assert status["outcome"] == "dry_run", status["failure"]
    run_dir = tmp_path / "runs" / EDITION_ID
    # A second run of the same id with the edition set aside: every story's brief still matches, so
    # nothing is written again.
    (run_dir / "edition.json").unlink()
    (run_dir / "edition-checked.json").unlink()
    fakes.writer_modes.clear()
    status = make_runner(policy, tmp_path, fakes, dry_run=True).run()
    assert status["outcome"] == "dry_run", status["failure"]
    assert fakes.writer_modes == []
    # The desk changes one story's sources: its brief differs, so that story alone is written again.
    (run_dir / "edition.json").unlink()
    (run_dir / "edition-checked.json").unlink()
    selection = read_json(run_dir / "selection.json")
    lead = next(s for s in selection["stories"] if s["role"] == "lead")
    lead["sources"] = lead["sources"][:-1]
    (run_dir / "selection.json").write_text(json.dumps(selection))
    status = make_runner(policy, tmp_path, fakes, dry_run=True).run()
    assert status["outcome"] == "dry_run", status["failure"]
    assert fakes.writer_modes == [("russian-frigate-flares-gedser", "write")]


def test_a_writer_whose_copy_cites_a_publisher_outside_its_sources_is_asked_again(policy, tmp_path):
    fakes = Fakes(tmp_path)
    seen = []

    def overciting_writer(brief_path, timeout):
        brief = read_json(brief_path)
        record = fakes.writer(brief_path, timeout)
        if brief["story"]["role"] == "lead":
            seen.append(brief.get("build_problem"))
            if not brief.get("build_problem"):
                copy = json.loads(record["result"])
                copy["standard"][0][1] = ["economist"]
                record["result"] = json.dumps(copy)
        return record

    status = make_runner(policy, tmp_path, fakes, writer=overciting_writer).run()
    assert status["outcome"] == "published", status["failure"]
    assert seen[0] is None and "economist" in seen[1]


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


# ---- verification of the review fixes: the four partial closures ------------------------------------


def _poisoning_editor(fakes):
    original = fakes.editor

    def editor(mode, run_dir, timeout):
        record = original(mode, run_dir, timeout)
        window = json.loads((run_dir / "window.json").read_text())
        for article in window["articles"]:
            article["description"] = "POISONED"
        (run_dir / "window.json").write_text(json.dumps(window))
        return record

    return editor


def test_rejected_evidence_is_quarantined_so_a_retry_rebuilds_it(policy, tmp_path):
    fakes = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, fakes, editor=_poisoning_editor(fakes)).run()
    assert status["failure"]["type"] == "input_modified"
    run_dir = tmp_path / "runs" / EDITION_ID
    assert not (run_dir / "window.json").exists(), "the modified evidence must not stay in place"
    assert not (run_dir / "edition.json").exists(), "artifacts built beside modified evidence go with it"
    quarantine = list(run_dir.glob("quarantine-*"))
    assert quarantine and (quarantine[0] / "window.json").exists()

    seen = {}
    original_checker = fakes.checker

    def checker(run_dir, timeout):
        seen["input"] = (run_dir / "check-input.json").read_text()
        return original_checker(run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, checker=checker, retry=True).run()
    assert status["outcome"] == "published", status["failure"]
    assert "POISONED" not in seen["input"]
    assert [c[1] for c in fakes.calls if c[0] == "editor"].count("desk") == 2


def test_inputs_changed_between_runs_are_caught_at_the_start_of_the_next(policy, tmp_path):
    fakes = Fakes(tmp_path, editor_hangs=True)
    make_runner(policy, tmp_path, fakes).run()
    run_dir = tmp_path / "runs" / EDITION_ID
    window = json.loads((run_dir / "window.json").read_text())
    window["articles"][0]["description"] = "EDITED BETWEEN RUNS"
    (run_dir / "window.json").write_text(json.dumps(window))
    again = Fakes(tmp_path)
    status = make_runner(policy, tmp_path, again, retry=True).run()
    assert status["failure"]["type"] == "input_modified" and status["failure"]["phase"] == "inputs"
    assert ("editor", "edition") not in again.calls
    status = make_runner(policy, tmp_path, again, retry=True).run()
    assert status["outcome"] == "published", status["failure"]


def _git_repo(tmp_path):
    import subprocess

    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@example.org")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("runs/\nvar/\nthreads.json\n")
    (tmp_path / "notes.txt").write_text("committed\n")
    git("add", ".gitignore", "notes.txt")
    git("commit", "-q", "-m", "seed")
    return git


def test_a_session_that_reverts_the_owners_edit_to_the_committed_text_is_caught(policy, tmp_path):
    from news_editorial.run import _stray_changes

    _git_repo(tmp_path)
    (tmp_path / "notes.txt").write_text("the owner's edit\n")
    fakes = Fakes(tmp_path)
    original = fakes.editor

    def editor(mode, run_dir, timeout):
        (tmp_path / "notes.txt").write_text("committed\n")  # back to HEAD: vanishes from git status
        return original(mode, run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: _stray_changes(tmp_path)).run()
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["details"]["paths"] == ["notes.txt"]


def test_a_session_that_touches_the_desks_ignored_state_is_caught(policy, tmp_path):
    from news_editorial.run import _stray_changes

    _git_repo(tmp_path)
    fakes = Fakes(tmp_path)
    fakes.registry.write_text('{"schema_version": 1, "threads": []}')
    original = fakes.editor

    def editor(mode, run_dir, timeout):
        fakes.registry.write_text('{"schema_version": 1, "threads": [{"id": "planted"}]}')
        return original(mode, run_dir, timeout)

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: _stray_changes(tmp_path)).run()
    assert status["failure"]["type"] == "stray_edits"
    assert status["failure"]["details"]["paths"] == ["threads.json"]


def test_the_guard_runs_even_when_the_session_raises_something_unexpected(policy, tmp_path):
    fakes = Fakes(tmp_path)
    tree = []

    def editor(mode, run_dir, timeout):
        tree.append("editorial/policy.yaml")
        raise OSError("disk full")

    status = make_runner(policy, tmp_path, fakes, editor=editor, stray_changes=lambda: list(tree)).run()
    assert status["failure"]["type"] == "stray_edits"


def test_schema_invalid_cached_verdicts_are_not_reused(policy, tmp_path):
    fakes = Fakes(tmp_path)
    original = fakes.checker

    def bad_checker(run_dir, timeout):
        record = original(run_dir, timeout)
        doc = json.loads((run_dir / "verdicts.json").read_text())
        doc["stories"][0]["sentences"][0]["verdict"] = "maybe"
        (run_dir / "verdicts.json").write_text(json.dumps(doc))
        return record

    status = make_runner(policy, tmp_path, fakes, checker=bad_checker).run()
    assert status["failure"]["type"] == "verdicts_invalid"
    status = make_runner(policy, tmp_path, fakes, retry=True).run()
    assert status["outcome"] == "published", status["failure"]
    assert fakes.checker_calls == 2


def test_a_descendant_that_ignores_term_is_still_killed_after_the_parent_exits(tmp_path, monkeypatch):
    from news_editorial import blocks
    from news_editorial.run import _headless

    monkeypatch.setattr(blocks, "GRACE_SECONDS", 0.3)
    marker = tmp_path / "marker"
    script = tmp_path / "parent.sh"
    script.write_text(f'#!/bin/sh\n(trap "" TERM; sleep 1.5; touch "{marker}") &\nexec sleep 5\n')
    script.chmod(0o755)
    with pytest.raises(RunFailure):
        _headless([str(script)], tmp_path, 0.3, "editor-edition", tmp_path, "editor_minutes")
    time.sleep(2)
    assert not marker.exists(), "a TERM-ignoring child outlived the timeout"
