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


HEALTHY = {"feeds": [{"feed_id": "dr.latest", "consecutive_failures": 0}, {"feed_id": "bbc.world", "consecutive_failures": 3}]}


def run(tmp_path, auths, claude, codex, checker="codex", health=HEALTHY, **config):
    claude_auth, codex_auth = auths
    codex_auth.codex_command = str(codex)
    return preflight({"editor_command": str(claude), "codex_command": str(codex), "checker": checker, **config}, claude_auth=claude_auth, codex_auth=codex_auth, health=health)


def test_every_login_working_is_ready_and_says_so(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, True, False))
    assert report["state"] == "ready"
    assert report["claude"]["primary"]["ok"] and report["claude"]["fallback"] is None and report["claude"]["usable"] == "token"
    assert report["codex"]["primary"]["ok"] and report["codex"]["usable"] == "chatgpt"
    subject, body = summary(report)
    assert "ready" in subject and body.startswith("claude: token ok\ncodex: ChatGPT login ok\nfeeds: 2 checked, none failing")
    assert report["feeds"] == {"checked": 2, "failing": []}


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


def model_recording_claude(tmp_path, dead_model=None):
    """Answers ok, records each model asked for, and fails like a retired model when asked for `dead_model`."""
    body = (
        'prev=""; for a in "$@"; do if [ "$prev" = "--model" ]; then echo "$a" >> "' + str(tmp_path / "models.txt") + '"; m=$a; fi; prev=$a; done\n'
        + (f'if [ "$m" = "{dead_model}" ]; then printf \'%s\\n\' \'{{"type":"result","is_error":true,"result":"API Error: 404 model not found"}}\'; exit 1; fi\n' if dead_model else "")
        + 'printf \'%s\\n\' \'{"type":"result","is_error":false,"result":"ok"}\'\n'
    )
    return fake_cli(tmp_path, "claude", body)


def test_the_probe_asks_for_every_production_model_once(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    claude = model_recording_claude(tmp_path)
    report = run(tmp_path, auths, claude, codex_that(tmp_path, True, False), editor_model="claude-opus-5-5", writer_model="claude-sonnet-5-5")
    assert (tmp_path / "models.txt").read_text().split() == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert report["claude"]["primary"]["models"] == ["claude-opus-5-5", "claude-sonnet-5-5"]


def test_a_retired_production_model_is_found_the_night_before(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    claude = model_recording_claude(tmp_path, dead_model="claude-opus-5-5")
    report = run(tmp_path, auths, claude, codex_that(tmp_path, True, False), editor_model="claude-opus-5-5")
    assert report["state"] == "not_ready" and report["claude"]["primary"]["detail"].startswith("claude-opus-5-5: ")
    assert "404" in summary(report)[1]


def test_without_a_configured_model_the_cheap_probe_model_is_used(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    run(tmp_path, auths, model_recording_claude(tmp_path), codex_that(tmp_path, True, False))
    assert (tmp_path / "models.txt").read_text().split() == ["claude-haiku-4-5-20251001"]


def test_the_codex_probe_passes_the_configured_checker_model(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    codex = fake_cli(tmp_path, "codex", 'printf \'%s\' "$*" > "' + str(tmp_path / "codex-argv.txt") + '"; prev=""; for a in "$@"; do if [ "$prev" = "-o" ]; then echo ok > "$a"; fi; prev=$a; done; exit 0\n')
    run(tmp_path, auths, model_recording_claude(tmp_path), codex, checker_model="gpt-6-astra")
    assert "-m gpt-6-astra" in (tmp_path / "codex-argv.txt").read_text()


def test_feeds_failing_more_than_twenty_polls_are_named(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    health = {"feeds": [
        {"feed_id": "dr.latest", "consecutive_failures": 0},
        {"feed_id": "altinget.by", "consecutive_failures": 37, "url": "https://www.altinget.dk/by/rss", "last_error_json": '{"type": "http_error", "message": "HTTP 404"}'},
        {"feed_id": "bbc.world", "consecutive_failures": 20},
        {"feed_id": "ft.home", "consecutive_failures": 96, "last_error_json": {"message": "name resolution failed"}},
    ]}
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, True, False), health=health)
    assert report["state"] == "ready"
    assert [f["feed_id"] for f in report["feeds"]["failing"]] == ["ft.home", "altinget.by"]
    assert report["feeds"]["failing"][1]["error"] == "HTTP 404" and report["feeds"]["checked"] == 4
    subject, body = summary(report)
    assert subject.endswith("; 2 feeds failing")
    assert "feeds FAILING, 2 of 4: ft.home (96 failed polls running: name resolution failed), altinget.by (37 failed polls running: HTTP 404)" in body


def test_unreadable_health_is_reported_not_fatal(tmp_path, auths):
    auths[0].token_path.write_text("sk-ant-oat01-ok\n")
    def broken():
        raise OSError("block 1 is locked")
    report = run(tmp_path, auths, claude_that(tmp_path, True, False), codex_that(tmp_path, True, False), health=broken)
    assert report["state"] == "ready" and "block 1 is locked" in report["feeds"]["error"]
    assert "feeds: health could not be read" in summary(report)[1]
