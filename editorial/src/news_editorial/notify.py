"""Tell the owner: a configured command, else a Discord webhook, else SMTP, else the desktop and stderr."""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .paths import VAR

SMTP_ENV = VAR / "smtp.env"
DISCORD_ENV = VAR / "discord.env"
DISCORD_LIMIT = 2000  # characters per message


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def discord_webhook_url(env: dict[str, str]) -> str | None:
    """The webhook from var/discord.env: a full URL, or an id and token. Placeholders left in the template do not count."""
    url = env.get("DISCORD_WEBHOOK_URL", "")
    if url.startswith("https://"):
        return url
    hook_id, token = env.get("DISCORD_WEBHOOK_ID", ""), env.get("DISCORD_WEBHOOK_TOKEN", "")
    if hook_id.isdigit() and token and "<" not in token and " " not in token:
        return f"https://discord.com/api/webhooks/{hook_id}/{token}"
    return None


def _post_json(url: str, payload: dict[str, Any]) -> int:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "copenhagen-daily-desk/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def notify(
    subject: str,
    body: str,
    config: dict[str, Any] | None = None,
    *,
    cwd: Path | None = None,
    smtp_env: Path = SMTP_ENV,
    discord_env: Path = DISCORD_ENV,
    post: Any = _post_json,
    desktop: bool = True,
) -> dict[str, Any]:
    config = config or {}
    command = config.get("command")
    if command:
        proc = subprocess.run([command, subject], input=body, text=True, cwd=cwd, capture_output=True, timeout=60)
        return {"delivered": "command", "exit_code": proc.returncode}
    webhook = discord_webhook_url(_read_env(discord_env)) if discord_env.is_file() else None
    if webhook:
        content = f"**{subject}**\n{body}"
        if len(content) > DISCORD_LIMIT:
            content = content[: DISCORD_LIMIT - 1] + "…"
        status = post(webhook, {"content": content})
        return {"delivered": "discord", "status": status}
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
