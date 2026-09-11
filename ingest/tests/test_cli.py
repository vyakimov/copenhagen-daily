from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from news_ingest.cli import SCHEMA_VERSION, main
from news_ingest.collect import process_lock
from news_ingest.db import Database


def invoke(capsys, argv):
    code = main(argv)
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured


def test_list_actions_is_sorted_and_self_describing(capsys):
    code, envelope, captured = invoke(capsys, ["list-actions"])
    assert code == 0
    assert captured.err == ""
    assert envelope["ok"] is True
    assert envelope["meta"]["schema_version"] == SCHEMA_VERSION
    actions = envelope["result"]["actions"]
    assert [action["name"] for action in actions] == sorted(action["name"] for action in actions)
    collect = next(action for action in actions if action["name"] == "collect")
    assert collect["mutates"] is True
    assert collect["network"] is True
    for action in actions:
        if action["mutates"]:
            assert any(param["name"] == "dry_run" for param in action["params"])


@pytest.mark.parametrize(
    ("argv", "action"),
    [
        ([], "unknown"),
        (["unknown-action"], "unknown"),
        (["export", "--output", "somewhere"], "export"),
    ],
)
def test_usage_failures_always_emit_json(capsys, argv, action):
    code, envelope, _ = invoke(capsys, argv)
    assert code == 2
    assert envelope["ok"] is False
    assert envelope["action"] == action
    assert envelope["error"]["type"] == "invalid_arguments"
    assert envelope["error"]["details"]["known_actions"]


def test_version_uses_normal_envelope(capsys):
    code, envelope, _ = invoke(capsys, ["--version"])
    assert code == 0
    assert envelope["action"] == "version"
    assert envelope["result"]["schema_version"] == SCHEMA_VERSION


def test_lock_busy_is_structured_and_precedes_database_mutation(capsys, config_path, tmp_path):
    database = tmp_path / "var" / "news.sqlite3"
    lock = tmp_path / "var" / "news.lock"
    config = tmp_path / "config" / "sources.yaml"
    config.parent.mkdir()
    config.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {database}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {lock}")
    )

    with process_lock(lock):
        code, envelope, _ = invoke(capsys, ["collect", "--config", str(config), "--once"])

    assert code == 1
    assert envelope["error"]["type"] == "lock_busy"
    assert not database.exists()


def test_validate_config_is_deterministic(capsys, config_path):
    argv = ["validate-config", "--config", str(config_path)]
    first = invoke(capsys, argv)[1]
    second = invoke(capsys, argv)[1]
    assert first == second
    assert first["result"]["enabled_sources"] == sorted(first["result"]["enabled_sources"])
    assert first["result"]["enabled_feed_ids"] == sorted(first["result"]["enabled_feed_ids"])


def test_collect_dry_run_rejects_unknown_source_without_creating_database(
    capsys, tmp_path, config_path
):
    text = config_path.read_text().replace("var/news-ingest.sqlite3", "var/missing.sqlite3")
    config = tmp_path / "config" / "sources.yaml"
    config.parent.mkdir()
    config.write_text(text)
    code, envelope, _ = invoke(
        capsys,
        ["collect", "--config", str(config), "--source", "wire-service", "--once", "--dry-run"],
    )
    assert code == 1
    assert envelope["error"]["type"] == "invalid_arguments"
    assert envelope["error"]["details"]["valid_values"]
    assert not (tmp_path / "var" / "missing.sqlite3").exists()


def test_export_dry_run_does_not_create_target(capsys, config_path, tmp_path):
    database = tmp_path / "var" / "news.sqlite3"
    lock = tmp_path / "var" / "news.lock"
    config = tmp_path / "config" / "sources.yaml"
    config.parent.mkdir()
    config.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {database}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {lock}")
    )
    Database(database).close()
    target = tmp_path / "edition"
    code, envelope, _ = invoke(
        capsys,
        [
            "export",
            "--config",
            str(config),
            "--since",
            "2026-09-07T00:00:00Z",
            "--until",
            "2026-09-08T00:00:00Z",
            "--output",
            str(target),
            "--dry-run",
        ],
    )
    assert code == 0
    assert envelope["result"]["dry_run"] is True
    assert envelope["result"]["mode"] == "publication_window"
    assert not target.exists()


def test_wrapper_export_smoke_uses_temporary_database(config_path, tmp_path):
    root = Path(__file__).parents[1]
    database = tmp_path / "var" / "news.sqlite3"
    lock = tmp_path / "var" / "news.lock"
    config = tmp_path / "config" / "sources.yaml"
    config.parent.mkdir()
    config.write_text(
        config_path.read_text()
        .replace("database_path: var/news-ingest.sqlite3", f"database_path: {database}")
        .replace("lock_path: var/news-ingest.lock", f"lock_path: {lock}")
    )
    Database(database).close()
    output_parent = tmp_path / "exports"
    output_parent.mkdir()
    output = output_parent / "empty"

    completed = subprocess.run(
        [
            str(root / "gather_news.sh"),
            "export",
            "--config",
            str(config),
            "--since",
            "2026-09-07T00:00:00Z",
            "--until",
            "2026-09-08T00:00:00Z",
            "--output",
            str(output),
        ],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    envelope = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert envelope["ok"] is True
    assert envelope["result"]["article_count"] == 0
    assert (output / "articles.jsonl").read_text() == ""
    assert (output / "manifest.json").is_file()


def test_wrapper_works_outside_repository():
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        [str(root / "gather_news.sh"), "validate-config"],
        cwd="/tmp",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    envelope = json.loads(completed.stdout)
    assert envelope["ok"] is True
    assert envelope["action"] == "validate-config"
