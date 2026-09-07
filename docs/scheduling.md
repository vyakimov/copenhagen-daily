# Scheduling

Run a five-minute external job such as `*/5 * * * * cd /path/news-gatherer && uv run news-ingest collect --once`. A systemd timer may invoke the same command with `OnUnitActiveSec=5min`; macOS launchd may use `StartInterval` set to 300. Schedule `news-ingest live-contracts` separately once daily. Do not install scheduler entries automatically.
