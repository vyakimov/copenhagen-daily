import json
import stat

import pytest

from news_editorial.paths import EDITORIAL, REPO
from news_editorial.run import RunFailure, invoke_checker, invoke_editor


def fake_cli(tmp_path, name, body):
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def recording_claude(tmp_path):
    return fake_cli(tmp_path, "claude", 'printf \'%s\' "$*" > "$PWD/argv.txt"\nprintf \'%s\\n\' \'{"type":"result","is_error":false,"num_turns":2,"session_id":"s","result":"done"}\'\n')


def test_editor_session_is_bounded_and_allowlisted(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    claude = recording_claude(tmp_path)
    record = invoke_editor("edition", run_dir, timeout=30, config={"editor_command": str(claude)}, max_turns=150)
    argv = (run_dir / "argv.txt").read_text()
    assert "--permission-mode acceptEdits" in argv
    wrapper = EDITORIAL / "edit_news.sh"
    assert f"--allowedTools Bash({wrapper} check-clusters *),Bash({wrapper} score *),Bash({wrapper} build *)" in argv
    assert f"Bash({wrapper} *)" not in argv and f"Bash({wrapper} run" not in argv
    assert "--disallowedTools WebFetch,WebSearch" in argv
    assert "--strict-mcp-config" in argv and "--max-turns 150" in argv
    assert "--no-session-persistence" in argv and "--output-format json" in argv
    assert f"--add-dir {REPO}" in argv
    assert str(REPO / "skills" / "editorial-desk" / "SKILL.md") in argv and "Mode: edition" in argv
    assert record["num_turns"] == 2
    assert list((run_dir / "sessions").glob("editor-edition-*.json"))


def test_checker_session_has_no_bash(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    claude = recording_claude(tmp_path)
    invoke_checker(run_dir, timeout=30, config={"checker": "claude", "editor_command": str(claude)}, max_turns=40)
    argv = (run_dir / "argv.txt").read_text()
    assert "--disallowedTools WebFetch,WebSearch,Bash" in argv
    assert "--strict-mcp-config" in argv and "--max-turns 40" in argv
    assert str(REPO / "skills" / "editorial-checker" / "SKILL.md") in argv


def test_codex_checker_writes_through_the_output_schema(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    codex = fake_cli(tmp_path, "codex", 'printf \'%s\' "$*" > "$PWD/argv.txt"\necho ok\n')
    invoke_checker(run_dir, timeout=30, config={"checker": "codex", "codex_command": str(codex)})
    argv = (run_dir / "argv.txt").read_text()
    assert argv.startswith("exec --skip-git-repo-check -s read-only --ephemeral --output-schema")
    assert (run_dir / "sessions" / "verdicts.strict.schema.json").exists()
    assert f"-o {run_dir / 'verdicts.json'}" in argv and str(EDITORIAL / "VERIFIER.md") in argv


def test_session_timeout_is_a_run_failure(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sleeper = fake_cli(tmp_path, "claude", "sleep 5\n")
    with pytest.raises(RunFailure) as info:
        invoke_editor("edition", run_dir, timeout=1, config={"editor_command": str(sleeper)})
    assert info.value.error_type == "editor_timeout"


def test_session_error_result_is_a_run_failure(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    failing = fake_cli(tmp_path, "claude", 'printf \'%s\\n\' \'{"type":"result","is_error":true,"result":"boom"}\'\n')
    with pytest.raises(RunFailure) as info:
        invoke_editor("edition", run_dir, timeout=5, config={"editor_command": str(failing)})
    assert info.value.error_type == "editor_failed"
