import stat

import pytest

from news_editorial.preflight import preflight, summary
from news_editorial.run import ClaudeAuth, CodexAuth


def fake_cli(tmp_path, name, body):
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def claude_that(tmp_path, token_ok, key_ok):
    """Answers ok or fails to authenticate, by which credential it was handed."""
    def verdict(ok):
        return ('printf \'%s\\n\' \'{"type":"result","is_error":false,"result":"ok","total_cost_usd":0.01}\'; exit 0\n' if ok
                else 'printf \'%s\\n\' \'{"type":"result","is_error":true,"result":"Failed to authenticate. API Error: 401"}\'; exit 1\n')
    return fake_cli(tmp_path, "claude",
                    'if [ -n "${CLAUDE_CODE_OAUTH_TOKEN-}" ]; then\n' + verdict(token_ok) + 'fi\n'
                    'if [ -n "${ANTHROPIC_API_KEY-}" ]; then\n' + verdict(key_ok) + 'fi\n'
                    'echo "Failed to authenticate: no login"; exit 1\n')


def codex_that(tmp_path, chatgpt_ok, key_ok):
    def verdict(ok):
        return ('for a in "$@"; do if [ "$prev" = "-o" ]; then echo ok > "$a"; fi; prev=$a; done; exit 0\n' if ok
                else 'echo "ERROR: unexpected status 401 Unauthorized: Missing bearer" >&2; exit 1\n')
    return fake_cli(tmp_path, "codex",
                    'if [ "$1" = "login" ]; then cat > "$CODEX_HOME/auth.json"; exit 0; fi\n'
                    'if [ -f "${CODEX_HOME-/nonexistent}/auth.json" ]; then\n' + verdict(key_ok) + 'fi\n' + verdict(chatgpt_ok))


@pytest.fixture
def auths(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claude = ClaudeAuth(token_path=tmp_path / "claude-oauth.env", key_path=tmp_path / "claude-api-key.env")
    codex = CodexAuth(key_path=tmp_path / "codex-api-key.env", key_home=tmp_path / "codex-api-home")
    return claude, codex


def run(tmp_path, auths, claude, codex, checker="codex"):
    claude_auth, codex_auth = auths
    codex_auth.codex_command = str(codex)
    return preflight({"editor_command": str(claude), "codex_command": str(codex), "checker": checker}, claude_auth=claude_auth, codex_auth=codex_auth)


def test_every_login_working_is_ready_and_says_so(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, True, False))
    assert report["state"] == "ready"
    assert report["claude"]["primary"]["ok"] and report["claude"]["fallback"] is None and report["claude"]["usable"] == "token"
    assert report["codex"]["primary"]["ok"] and report["codex"]["usable"] == "chatgpt"
    subject, body = summary(report)
    assert "ready" in subject and body.startswith("claude: token ok\ncodex: ChatGPT login ok")


def test_a_dead_token_with_a_working_key_is_ready_on_fallback(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-stale\n")
    auths[0].key_path.write_text("sk-ant-api03-key\n")
    report = run(tmp_path, auths, claude_that(tmp_path, False, True), codex_that(tmp_path, True, False))
    assert report["state"] == "ready_on_fallback" and report["claude"]["usable"] == "api_key"
    assert report["claude"]["primary"]["ok"] is False and "401" in report["claude"]["primary"]["detail"]
    assert report["claude"]["fallback"]["ok"] is True
    subject, body = summary(report)
    assert "API key" in subject and "claude: token FAILED (" in body and "; API key ok" in body


def test_a_missing_token_counts_as_a_failed_primary(tmp_path, auths):
    auths[0].key_path.write_text("sk-ant-api03-key\n")
    report = run(tmp_path, auths, claude_that(tmp_path, False, True), codex_that(tmp_path, True, False))
    assert report["state"] == "ready_on_fallback" and "no token" in report["claude"]["primary"]["detail"]


def test_codex_failing_on_both_is_not_ready(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    auths[1].key_path.write_text("sk-proj-key\n")
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, False, False))
    assert report["state"] == "not_ready" and report["codex"]["usable"] is None
    assert report["codex"]["fallback"]["ok"] is False and "401" in report["codex"]["fallback"]["detail"]
    assert (auths[1].key_home / "auth.json").read_text() == "sk-proj-key"
    subject, body = summary(report)
    assert "CANNOT" in subject and "codex: ChatGPT login FAILED (" in body and "; API key FAILED (" in body


def test_without_a_key_the_fallback_is_reported_as_absent(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-stale\n")
    report = run(tmp_path, auths, claude_that(tmp_path, False, False), codex_that(tmp_path, True, False))
    assert report["state"] == "not_ready" and "no key" in report["claude"]["fallback"]["detail"]


def test_a_claude_checker_means_codex_is_not_probed(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, False, False), checker="claude")
    assert report["state"] == "ready" and "codex" not in report
