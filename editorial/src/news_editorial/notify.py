"""Tell the owner when something went wrong: a configured command, else SMTP, else the desktop and stderr."""

from __future__ import annotations

import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .paths import VAR

SMTP_ENV = VAR / "smtp.env"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def notify(
    subject: str,
    body: str,
    config: dict[str, Any] | None = None,
    *,
    cwd: Path | None = None,
    smtp_env: Path = SMTP_ENV,
    desktop: bool = True,
) -> dict[str, Any]:
    config = config or {}
    command = config.get("command")
    if command:
        proc = subprocess.run([command, subject], input=body, text=True, cwd=cwd, capture_output=True, timeout=60)
        return {"delivered": "command", "exit_code": proc.returncode}
    if smtp_env.is_file():
        env = _read_env(smtp_env)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = env.get("MAIL_FROM", env.get("SMTP_USER", ""))
        message["To"] = env.get("MAIL_TO", env.get("MAIL_FROM", ""))
        message.set_content(body)
        with smtplib.SMTP(env.get("SMTP_HOST", "smtp.gmail.com"), int(env.get("SMTP_PORT", "587")), timeout=30) as smtp:
            smtp.starttls()
            if env.get("SMTP_USER"):
                smtp.login(env["SMTP_USER"], env.get("SMTP_PASSWORD", ""))
            smtp.send_message(message)
        return {"delivered": "smtp", "to": message["To"]}
    if desktop and os.path.exists("/usr/bin/osascript"):
        script = f'display notification "{body[:180].replace(chr(34), chr(39))}" with title "{subject.replace(chr(34), chr(39))}"'
        subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, timeout=10)
    sys.stderr.write(f"NOTIFY {subject}\n{body}\n")
    return {"delivered": "stderr"}
