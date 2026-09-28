import stat

from news_editorial.notify import notify


def test_notify_runs_the_configured_command_with_subject_and_body(tmp_path):
    script = tmp_path / "notify.sh"
    script.write_text('#!/bin/sh\nprintf "%s\\n" "$1" > "$PWD/subject.txt"\ncat > "$PWD/body.txt"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    result = notify("Edition failed", "phase editor: editor_timeout", {"command": str(script)}, cwd=tmp_path)
    assert result["delivered"] == "command"
    assert (tmp_path / "subject.txt").read_text().strip() == "Edition failed"
    assert "editor_timeout" in (tmp_path / "body.txt").read_text()


def test_notify_falls_back_to_the_log_when_nothing_is_configured(tmp_path, capsys):
    result = notify("Edition failed", "body", {}, cwd=tmp_path, smtp_env=tmp_path / "missing.env", desktop=False)
    assert result["delivered"] == "stderr"
    assert "Edition failed" in capsys.readouterr().err


def test_notify_reads_smtp_settings_from_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / "smtp.env"
    env.write_text("SMTP_HOST=smtp.example.org\nSMTP_PORT=587\nSMTP_USER=u\nSMTP_PASSWORD=p\nMAIL_FROM=a@example.org\nMAIL_TO=b@example.org\n")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=0):
            sent["host"], sent["port"] = host, port
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self):
            sent["tls"] = True
        def login(self, user, password):
            sent["login"] = (user, password)
        def send_message(self, message):
            sent["subject"] = message["Subject"]; sent["to"] = message["To"]

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    result = notify("Edition failed", "body", {}, cwd=tmp_path, smtp_env=env, desktop=False)
    assert result["delivered"] == "smtp"
    assert sent == {"host": "smtp.example.org", "port": 587, "tls": True, "login": ("u", "p"), "subject": "Edition failed", "to": "b@example.org"}
