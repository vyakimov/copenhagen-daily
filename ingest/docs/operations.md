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

## Persistent merge state

Migration 004 creates two disposable derived tables: `article_feed_merge_state`
and `article_merge_heads`. No original observations are rewritten or removed.
Initialization is lazy: the next successful `200` observation of an article reads
its retained history once and records all contributing feeds. Further observations
read only new sightings after the article's saved sighting-ID watermark. A `304`
does not initialize or change merge state. Expect elevated history reads during
the first collections after upgrading, including when an old article reappears.

Each feed state stores at most ten distinct representative snapshots (the overall
winner and nonempty field winners), plus category/keyword unions and observation
timestamp bounds. Usually one snapshot supplies most fields. Storage scales with
contributing feeds and distinct retained categories/keywords, not the number of
repeated observations. Original timestamps and stable sighting order are retained
so field ties, missing-value fallbacks, authors, and raw metadata remain exact.
Priorities are applied when combining feeds, not baked into the cache. Changing
priorities therefore reevaluates each article on its next observation without
rereading its history. Configured disabled feeds remain part of that history;
removing a historical feed's configuration still requires explicit resolution.

State, watermark, sightings, projection, versions, appearances, and HTTP validators
share the same per-feed transaction. Failed ingestion rolls all of them back.
A missing cache/head or structurally invalid cache triggers reconstruction for
that identity. A full rebuild always derives from original sightings, independently
compares the cached algorithm's result, and replaces the selected source's cache
on apply. Dry-run reports `merge_states_rebuilt` (the number staged) but makes no
persistent changes; projection difference counts do not measure cache differences.
Apply installs missing schema migrations before staging; dry-run never migrates.
