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

## Rebuilding article projections

Use retained normalized sightings to compare or repair the current article table:

```sh
./gather_news.sh rebuild-articles --dry-run
./gather_news.sh rebuild-articles --source dr --dry-run
./gather_news.sh rebuild-articles --source dr
```

Dry-run opens a read-only, consistent database snapshot and stages its calculations
in connection-local temporary tables. It reports `rows_added`, `rows_removed`,
`rows_changed`, resulting `article_count`, and `blocked_removals`, both overall and
in `by_source`, plus `sightings_read`. Changes include observation/provenance fields
and derived database columns, not just content hashes; JSON key order is ignored.
An unchanged projection reports zero differences.

Apply acquires the collector's process lock, reconstructs the selected projection,
then reconciles it in one transaction. Other readers see the old or new committed
projection, never a partial rebuild. Keep a verified backup before operational
repairs. A rebuild can be expensive on a large history and blocks collection while
the lock is held; schedule it accordingly. Dry-run does not take that process lock,
but a long-lived read snapshot can delay WAL reclamation.

Rebuild uses the same merge/hash rules as collection, replaying each identity in
sighting-ID order. It derives `last_changed_at` from the stored observation time of
the last content transition, not the rebuild time. It does not append, replace, or
remove article versions and never changes sightings, payloads, appearances, HTTP
validators, or poll state. Existing enrichment tracking columns are preserved.
Source filtering also limits which sightings are validated. Configured disabled
sources/feeds remain usable for reconstruction; a missing historical feed causes
`rebuild_unknown_feed` rather than an invented priority. Use the intended configuration
when rebuilding: changed feed priorities can intentionally change the projection.

Invalid sightings produce `rebuild_invalid_sighting` and leave the projection
untouched. If an article has versions but no sightings, dry-run reports it in
`blocked_removals`; apply fails with `rebuild_conflict` rather than deleting version
history or breaking its references. Investigate the missing evidence first.

Rebuild uses normalized sightings, not a fresh parse of raw RSS. It cannot repair
lost or incorrectly normalized sightings; raw-payload replay remains a separate,
currently disabled command.
