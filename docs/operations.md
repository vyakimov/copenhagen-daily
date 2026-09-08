# Operations

After the operator provisions `.venv` from the committed lockfile, run every
workflow through `./gather_news.sh`. The absolute script path is suitable for an
allowlist and works from any current directory. Run `list-actions` for the
machine-readable action/parameter catalog and `validate-config` before any
network request.

Use `collect --once --dry-run` to inspect planned feeds and `collect --once` for
a real poll. Use `health` for status. Preview `export` and `backup` with
`--dry-run`; both refuse to overwrite an existing target. Verify backups with
`restore-check --backup PATH`. Run the complete offline validation suite with
`./gather_news.sh check`.

Every non-help call emits one JSON envelope on stdout. Branch on `ok` and
`error.type`; diagnostics go to stderr. Usage failures exit 2, other failures
exit 1, and success exits 0. The wrapper never prompts or invokes `uv`.

Raw RSS payloads can consume disk; monitor `var/`, rotate stderr logs externally,
and alert on health warnings. Copy SQLite backups or immutable exports, not the
live SQLite main file without its WAL. To upgrade: stop the scheduler, create a
backup, have the operator provision the locked environment, run
`./gather_news.sh check`, restart, and inspect health. Quarantine records contain
diagnostics rather than article text.
