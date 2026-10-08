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
    monkeypatch.setattr(run_module, "API_KEY_PATH", tmp_path / "claude-api-key.env")
    monkeypatch.setattr(run_module, "AUTH", run_module.ClaudeAuth())
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


# -- the API key as the fallback --------------------------------------------------------------------

def credential_recording_claude(tmp_path, token_fails=True):
    """Records which credential each call carried; a call on the token fails to authenticate when told to."""
    body = (
        'printf \'%s|%s\\n\' "${CLAUDE_CODE_OAUTH_TOKEN-unset}" "${ANTHROPIC_API_KEY-unset}" >> "$PWD/credentials.txt"\n'
        + ('if [ -n "${CLAUDE_CODE_OAUTH_TOKEN-}" ]; then printf \'%s\\n\' \'{"type":"result","is_error":true,"result":"Failed to authenticate. API Error: 401 OAuth access token is invalid."}\'; exit 1; fi\n' if token_fails else "")
        + 'printf \'%s\\n\' \'{"type":"result","is_error":false,"result":"done"}\'\n'
    )
    return fake_cli(tmp_path, "claude", body)


@pytest.fixture
def auth(tmp_path, token_file, monkeypatch):
    from news_editorial.run import ClaudeAuth
    notes = []
    auth = ClaudeAuth(token_path=token_file, key_path=tmp_path / "claude-api-key.env", notifier=lambda subject, body: notes.append((subject, body)))
    auth.notes = notes
    return auth


def test_a_session_that_fails_on_the_token_is_rerun_on_the_api_key_and_the_run_stays_there(tmp_path, token_file, auth):
    token_file.write_text("sk-ant-oat01-stale\n")
    auth.key_path.write_text("sk-ant-api03-key\n")
    claude = credential_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, auth=auth)
    assert record["result"] == "done" and record["auth"] == "api_key"
    assert (run_dir / "credentials.txt").read_text() == "sk-ant-oat01-stale|unset\nunset|sk-ant-api03-key\n"
    assert len(auth.notes) == 1 and "API key" in auth.notes[0][0] and "stale" not in auth.notes[0][1]
    fallback = json.loads((run_dir / "sessions" / "auth-fallback.json").read_text())
    assert fallback["reason"] == "token_rejected" and fallback["session"].startswith("editor-desk-")
    # the next session of the run goes straight to the key, no second notification
    (run_dir / "credentials.txt").unlink()
    invoke_checker(run_dir, timeout=30, config={"checker": "claude", "editor_command": str(claude)}, auth=auth)
    assert (run_dir / "credentials.txt").read_text() == "unset|sk-ant-api03-key\n"
    assert len(auth.notes) == 1
    # both attempts of the first session are on record
    names = sorted(p.name for p in (run_dir / "sessions").glob("editor-desk-*.json"))
    assert len(names) == 2 and any(n.endswith("-api-key.json") for n in names)


def test_a_missing_token_file_falls_back_to_the_key_before_the_first_session(tmp_path, token_file, auth):
    auth.key_path.write_text("ANTHROPIC_API_KEY=sk-ant-api03-key\n")
    claude = credential_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, auth=auth)
    assert (run_dir / "credentials.txt").read_text() == "unset|sk-ant-api03-key\n"
    assert len(auth.notes) == 1 and "no token" in auth.notes[0][1]
    assert json.loads((run_dir / "sessions" / "auth-fallback.json").read_text())["reason"] == "token_missing"


def test_a_new_run_tries_the_token_again(tmp_path, token_file, auth):
    from news_editorial.run import ClaudeAuth
    token_file.write_text("sk-ant-oat01-fresh\n")
    auth.key_path.write_text("sk-ant-api03-key\n")
    auth.on_key = True  # the previous run ended on the key
    fresh = ClaudeAuth(token_path=token_file, key_path=auth.key_path, notifier=auth.notifier)
    claude = credential_recording_claude(tmp_path, token_fails=False)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, auth=fresh)
    assert (run_dir / "credentials.txt").read_text() == "sk-ant-oat01-fresh|unset\n"
    assert auth.notes == []


def test_without_a_key_an_auth_failure_is_the_usual_run_failure(tmp_path, token_file, auth):
    token_file.write_text("sk-ant-oat01-stale\n")
    claude = credential_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(RunFailure) as info:
        invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, auth=auth)
    assert info.value.error_type == "editor_failed"
    assert auth.notes == [] and not (run_dir / "sessions" / "auth-fallback.json").exists()


def test_a_session_that_fails_for_another_reason_is_not_rerun_on_the_key(tmp_path, token_file, auth):
    token_file.write_text("sk-ant-oat01-ok\n")
    auth.key_path.write_text("sk-ant-api03-key\n")
    failing = fake_cli(tmp_path, "claude", 'printf \'%s\\n\' \'{"type":"result","is_error":true,"result":"boom"}\'\n')
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(RunFailure):
        invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(failing)}, auth=auth)
    assert auth.notes == [] and not auth.on_key


def test_the_fallback_notification_is_delivered_even_if_the_notifier_raises(tmp_path, token_file, auth, capsys):
    def broken(subject, body):
        raise OSError("discord is down")
    auth.notifier = broken
    auth.key_path.write_text("sk-ant-api03-key\n")
    claude = credential_recording_claude(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    invoke_editor("desk", run_dir, timeout=30, config={"editor_command": str(claude)}, auth=auth)
    assert "discord is down" in capsys.readouterr().err
    assert (run_dir / "sessions" / "auth-fallback.json").exists()


def test_the_codex_checker_sees_neither_credential(tmp_path, token_file, auth):
    auth.key_path.write_text("sk-ant-api03-key\n")
    auth.on_key = True
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    codex = fake_cli(tmp_path, "codex", 'printf \'%s|%s\' "${CLAUDE_CODE_OAUTH_TOKEN-unset}" "${ANTHROPIC_API_KEY-unset}" > "$PWD/credentials.txt"\necho ok\n')
    invoke_checker(run_dir, timeout=30, config={"checker": "codex", "codex_command": str(codex)}, auth=auth)
    assert (run_dir / "credentials.txt").read_text() == "unset|unset"
