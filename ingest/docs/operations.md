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

Every non-help call emits one JSON envelope on stdout and nothing else; there
is no separate log stream. Branch on `ok` and `error.type`. Usage failures
exit 2, other failures exit 1, and success exits 0. The wrapper never prompts or
invokes `uv`. A failed feed's error is stored as JSON on its `feed_polls` row
and in `feed_state.last_error_json`, and each failure increments
`feed_state.consecutive_failures`; a successful or `304` poll resets the count.
`health` returns `status: degraded` with `feed_failures:<feed_id>` in `reasons`
for every feed at or above `failure_alert_threshold` (3 in
`config/sources.yaml`), and `integrity_check_failed` when SQLite's integrity
check fails. `export` waits up to 90 seconds for the collector's process lock
and holds it while reading, so a poll in flight delays an export rather than
racing it.

Raw payloads and sightings consume disk; monitor `var/`. `compact-history`
(below) bounds their growth. launchd writes the
collector's stdout and stderr to `~/Library/Logs/copenhagen-daily/`; rotate
those files externally. Alert on `health` returning `degraded` and read its
`reasons`. Copy SQLite backups or immutable exports, not the
live SQLite main file without its WAL. To upgrade: stop the scheduler, create a
backup, have the operator provision the locked environment, run
`./gather_news.sh check`, restart, and inspect health. Quarantine rows keep the
error and the raw feed item that failed, never a fetched article page.

## Collection performance

The collector runs every fifteen minutes under launchd (see
`scheduling.md`). Overlapping polls fail fast on the process lock and are
harmless. Freshness depends on the last completed collection; the schedule does
not guarantee a fifteen-minute bound.

`collect --once` reports `timings_seconds` and the counters defined in the
README. With the merge-state cache of migration 004 warm, an article's
observation reads only sightings after its saved watermark, so
`historical_rows_read` tracks `sightings_inserted` and a poll spends about 3
seconds in the database; fetch is the larger cost. A cold cache (a first
observation, or an old article reappearing) reads that identity's retained
history once and counts in `merge_state_bootstraps`.

The live database uses the migration 005 layout: `sightings` rows are thin
observation rows that reference shared `sighting_contents`, so a poll that sees
unchanged items adds rows without repeating their content. The database was
migrated with `deduplicate-sightings` and vacuumed on 30 September 2026.
`compact-history` runs daily (see "History compaction"); the pages it frees are
reused by later writes, so the file stops growing until they are used up.
`VACUUM` to return them to the filesystem is a separate step needing disk
headroom for a full copy.

Do not shorten raw payload retention to save space: compressed payloads are
small and are the audit trail; `compact-history` archives them instead. Do not lengthen the poll interval to reduce
load; fifteen minutes is the intended cadence for ten-item feeds.

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
Each state (schema version 2) also holds `revised_at`: when each field, and the
winning snapshot's own content, last changed within that feed. Combining feeds,
the newest revision wins and unrevised values fall back to priority, so polling
the same unchanged article in several feeds writes no versions. The revision
times cannot be recovered from a version-1 state, which therefore fails validation
and is rebuilt from history like any invalid cache.
Priorities are applied when combining feeds, not baked into the cache. Changing
priorities therefore reevaluates each article on its next observation without
rereading its history. Configured disabled feeds remain part of that history;
removing a historical feed's configuration still requires explicit resolution.

State, watermark, sightings, projection, versions, appearances, and HTTP validators
share the same per-feed transaction. Failed ingestion rolls all of them back.
A missing cache/head or structurally invalid cache triggers reconstruction for
that identity. A full rebuild always derives from original sightings by the same
per-feed replay that collection uses, verifies that the persisted (JSON) form of
the resulting states merges to the same article, and replaces the selected source's cache
on apply. Dry-run reports `merge_states_rebuilt` (the number staged) but makes no
persistent changes; projection difference counts do not measure cache differences.
Apply installs missing schema migrations before staging; dry-run never migrates.

### Upgrading to revision-ranked merge state (9 October 2026)

This upgrade changes `content_hash` (it no longer covers `description_source`)
and the cache format. Collecting with the new code before reconciling would
bootstrap every article it sees and write one version per article for the hash
change alone. Pause the collector, rebuild, then resume:

```sh
launchctl bootout gui/$(id -u)/ai.copenhagen-daily.collect
./gather_news.sh backup --output var/pre-revision-merge-YYYY-MM-DD.sqlite3
./gather_news.sh rebuild-articles --dry-run   # every article reports changed
./gather_news.sh rebuild-articles             # also installs migration 006
./gather_news.sh rebuild-articles --dry-run   # expect rows_changed 0
./gather_news.sh compact-history --vacuum     # first compaction, then VACUUM
editorial/config/launchd/install.sh           # reloads every job, adds the compact job
```

`install.sh` boots every job out and back in, collection included.

On a copy of the 9 October database (2.98 million sightings, 28,782 articles),
each rebuild took about 8.5 minutes and wrote no versions. The merge re-derives
each sighting's canonical URL from its raw URL with the current rules, so
rebuilt WSJ projections lose `mod` and the next clean sighting is not a revision;
stored sightings keep their original text. Any `export --changed-since` consumer
needs a fresh baseline afterwards: every hash changes, while rebuilt
`last_changed_at` values can move backwards.

## Content deduplication (migration 005)

Use `deduplicate-sightings --dry-run` to scan a consistent read-only snapshot and
measure unique content. It reports repeated JSON bytes, unique content JSON bytes,
per-observation JSON bytes, and estimated JSON bytes saved. These are payload
measurements, excluding keys, indexes, page overhead, and unchanged thin-row columns.
`database_allocated_bytes` and `database_free_bytes` report SQLite pages separately;
WAL size is not included. On an already migrated database the payload calculation
still compares its logically reconstructed legacy representation with deduplication.

Apply with `deduplicate-sightings --backup PATH`, choosing a new backup filename
whose parent directory exists. It acquires the collector lock before backup and
migration, uses SQLite's backup API, verifies backup integrity, and refuses to
overwrite the backup. Schedule the operation for a maintenance window: collection
cannot write while it runs. Allow space for the full backup, new tables, and WAL.

Populated databases do **not** run migration 005 during normal collection or rebuild.
Both layouts remain supported until this explicit command is used. Empty/new
databases migrate automatically. The migration runner places schema changes,
content transfer, indexes, and migration bookkeeping in one transaction; failure
rolls back to the legacy schema and data. A successful result includes
`sightings_verified`, `distinct_contents`, and `sightings_sha256`.

Each observation retains its original ID, poll/feed/source identity, placement,
publisher order, and observed-at timestamp. Its three normalized observation-time
values are factored into `observation_json`, preserving their original JSON literals.
`sighting_contents` stores the normalized JSON template and both original raw JSON
columns, keyed by a separate SHA-256 storage digest scoped to publisher/article
identity. Only those three top-level observation values are factored out: publisher
timestamps, raw URLs, nested metadata, key order, and whitespace remain untouched.
Every original JSON string reconstructs byte for byte. Hash matches are also checked
against the actual stored text; mismatches abort instead of reusing the wrong content.

Before committing, the migration compares ordered fingerprints covering every
original and reconstructed sighting column, verifies row counts and foreign keys,
and preserves the autoincrement high-water mark. It does not change article versions,
projections, appearances, payloads, validators, or merge-state watermarks. Future
content inserts and their observation references share the normal feed transaction;
unchanged observations still create sightings but reuse content.

Internal callers should use `db.read_sightings()` for logical observations. Physical
SQL queries must join `sightings.content_id` to `sighting_contents`; the old three JSON
columns no longer exist in `sightings`. Older application versions cannot read the
new layout. For rollback, stop database writers and restore the verified pre-migration
backup using the normal SQLite recovery procedure; do not copy a main file over an
active WAL database.

No compaction is performed automatically. Freed pages are reusable inside SQLite;
returning that space to the filesystem is a separate, post-validation maintenance
step. Existing raw-payload retention is unchanged.

## History compaction (migration 006)

`compact-history` runs daily at 03:15 under launchd
(`ai.copenhagen-daily.compact`) and touches only history older than
`compact_after_days` (seven). It holds the process lock, so a collection that
starts meanwhile fails fast with `lock_busy` and the next one catches up.

```sh
./gather_news.sh compact-history --dry-run   # counts only, read-only snapshot
./gather_news.sh compact-history             # archive and fold
./gather_news.sh compact-history --vacuum    # then return freed pages to the filesystem
```

- **Raw payloads.** Each feed's bodies from one UTC day become one xz archive in
  `raw_payload_archives`, with a `raw_payload_members` row per body. Every body is
  checked against its hash inside the archive before its gzip row is deleted, in
  the same transaction. `db.read_raw_payload()` reads a body from either place, and
  collection never stores an archived body again.
- **Sightings and appearances.** An unbroken run of identical rows for one article
  in consecutive successful polls of one feed keeps its first and last rows;
  `run_polls` on the first counts the polls covered. For sightings "identical" means
  the same `content_id`; for appearances, the same position, order and prominence.
  A `304` or failed poll does not break a run, while a successful poll without the
  article does. `read_sightings()` returns the kept rows, and `export` restores the
  removed appearances from `feed_polls`, so bundles are byte-identical before and
  after. A removed sighting's parse-time timestamps are not kept.

Each feed (or feed-day) commits separately, so an interrupted run leaves the rest
for the next one. SQLite reuses the freed pages, so the file stops growing until
they are used up; `--vacuum` needs free disk for a full copy of the compacted file.

On a copy of the 9 October database the first run took about 2.5 minutes. It
archived 24,585 bodies (234.5 MB of gzips into 19.0 MB), removed 1,021,494
sightings and 825,836 appearances, and left exports of three windows
byte-identical and `rebuild-articles --dry-run` at zero changes. A compacted day
keeps about 4% of its sightings and 20% of its appearances, and its payloads take
about 2 MB, so steady-state growth is about 75 MB a day, mostly
`sighting_contents`. `VACUUM` on that copy took under a minute.
