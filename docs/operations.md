# Operations

Run `uv sync --locked`, then `uv run news-ingest validate-config` before any network request. Use `collect --once` for a single poll, `health` for status, and `export` to publish an immutable bundle. Back up with `backup --output PATH`; verify a copy with `restore-check --backup PATH`.

Raw RSS payloads can consume disk; monitor `var/`, rotate stderr logs externally, and alert on health warnings. Copy SQLite backups or immutable exports, not the live SQLite main file without its WAL. To upgrade: stop the scheduler, create a backup, sync/test/migrate, restart, and inspect health. Quarantine records contain diagnostics rather than article text.
