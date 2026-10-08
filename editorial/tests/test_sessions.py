import json
import stat

import pytest

from news_editorial.paths import EDITORIAL, REPO
from news_editorial.run import RunFailure, invoke_checker, invoke_editor, invoke_writer


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
    record = invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, max_turns=150)
    argv = (run_dir / "argv.txt").read_text()
    assert "--permission-mode acceptEdits" in argv
    wrapper = EDITORIAL / "edit_news.sh"
    assert f"--allowedTools Bash({wrapper} check-clusters *),Bash({wrapper} score *)" in argv
    assert "build" not in argv
    assert f"Bash({wrapper} *)" not in argv and f"Bash({wrapper} run" not in argv
    assert "--disallowedTools WebFetch,WebSearch" in argv
    assert "--strict-mcp-config" in argv and "--max-turns 150" in argv
    assert "--no-session-persistence" in argv and "--output-format json" in argv
    assert f"--add-dir {REPO}" in argv
    assert str(REPO / "skills" / "editorial-desk" / "SKILL.md") in argv and "Mode: desk" in argv
    assert record["num_turns"] == 2
    assert list((run_dir / "sessions").glob("editor-desk-*.json"))


def test_writer_session_can_only_read_inside_its_own_directory(tmp_path):
    run_dir = tmp_path / "run"
    brief = run_dir / "stories" / "a-story" / "brief.json"
    brief.parent.mkdir(parents=True)
    brief.write_text("{}")
    claude = recording_claude(tmp_path)
    record = invoke_writer(brief, timeout=30, config={"editor_command": str(claude), "editor_model": "claude-opus-5-5"}, max_turns=20)
    argv = (brief.parent / "argv.txt").read_text()  # the session's working directory is the story's
    assert "--tools Read" in argv and "--add-dir" not in argv
    assert "--disallowedTools Bash,Write,Edit,MultiEdit,NotebookEdit,WebFetch,WebSearch,Agent,Task" in argv
    assert "--permission-mode" not in argv and "--allowedTools" not in argv
    assert "--max-turns 20" in argv and "--model claude-opus-5-5" in argv
    assert "Read brief.json in your working directory" in argv and str(REPO) not in argv
    assert record["result"] == "done"
    assert list((run_dir / "sessions").glob("writer-a-story-*.json"))


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
        invoke_editor("desk", run_dir, timeout=1, config={"editor_command": str(sleeper)})
    assert info.value.error_type == "editor_timeout"


def test_session_error_result_is_a_run_failure(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    failing = fake_cli(tmp_path, "claude", 'printf \'%s\\n\' \'{"type":"result","is_error":true,"result":"boom"}\'\n')
    with pytest.raises(RunFailure) as info:
        invoke_editor("desk", run_dir, timeout=5, config={"editor_command": str(failing)})
    assert info.value.error_type == "editor_failed"


def token_recording_claude(tmp_path):
    return fake_cli(tmp_path, "claude", 'printf \'%s\' "${CLAUDE_CODE_OAUTH_TOKEN-unset}" > "$PWD/token.txt"\nprintf \'%s\\n\' \'{"type":"result","is_error":false,"result":"done"}\'\n')


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    from news_editorial import run as run_module
    path = tmp_path / "claude-oauth.env"
    monkeypatch.setattr(run_module, "OAUTH_TOKEN_PATH", path)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    return path


def test_claude_sessions_get_the_long_lived_token_from_var(tmp_path, token_file):
    token_file.write_text("# the token from `claude setup-token`\nsk-ant-oat01-abc\n")
    claude = token_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    brief = run_dir / "stories" / "a-story" / "brief.json"
    brief.parent.mkdir(parents=True)
    brief.write_text("{}")
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)})
    assert (run_dir / "token.txt").read_text() == "sk-ant-oat01-abc"
    invoke_writer(brief, timeout=30, config={"editor_command": str(claude)})
    assert (brief.parent / "token.txt").read_text() == "sk-ant-oat01-abc"
    (run_dir / "token.txt").unlink()
    invoke_checker(run_dir, timeout=30, config={"checker": "claude", "editor_command": str(claude)})
    assert (run_dir / "token.txt").read_text() == "sk-ant-oat01-abc"


def test_token_file_may_use_the_env_assignment_form(tmp_path, token_file):
    token_file.write_text('CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-xyz"\n')
    claude = token_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)})
    assert (run_dir / "token.txt").read_text() == "sk-ant-oat01-xyz"


def test_without_the_token_file_sessions_use_the_cli_login(tmp_path, token_file):
    claude = token_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)})
    assert (run_dir / "token.txt").read_text() == "unset"


def test_codex_checker_never_sees_the_token(tmp_path, token_file):
    token_file.write_text("sk-ant-oat01-abc\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    codex = fake_cli(tmp_path, "codex", 'printf \'%s\' "${CLAUDE_CODE_OAUTH_TOKEN-unset}" > "$PWD/token.txt"\necho ok\n')
    invoke_checker(run_dir, timeout=30, config={"checker": "codex", "codex_command": str(codex)})
    assert (run_dir / "token.txt").read_text() == "unset"
