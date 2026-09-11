# Scheduling

Run the absolute allowlisted wrapper every five minutes, for example
`*/5 * * * * /path/copenhagen-today/ingest/gather_news.sh collect --once`. The wrapper
resolves its own repository, so the scheduler does not need `cd`, `uv`, or an
activated environment. A systemd timer may use the same command with
`OnUnitActiveSec=5min`; macOS launchd may use `StartInterval` set to 300.

Schedule `/path/copenhagen-today/ingest/gather_news.sh live-contracts` separately once
daily when that release-gated action is implemented. Its current explicit
`disabled` result does not constitute a live check. Do not install scheduler
entries automatically.
