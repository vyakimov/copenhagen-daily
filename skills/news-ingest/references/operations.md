# Operations reference

Read this file for running or diagnosing the `ingest/` collector. The authoritative action schema is always:

```sh
./gather_news.sh list-actions
```

## Action guide

| Action | Side effects | Use |
|---|---:|---|
| `validate-config` | none | Validate YAML, source constraints, paths, and show configured sources/feeds. Run before network work. |
| `collect --once` | network + database | Poll all enabled feeds. Add `--source ID` only for deliberate filtering. |
| `health` | none | Read SQLite integrity and per-feed state. `reasons` names each feed whose `consecutive_failures` reached the threshold (3) as `feed_failures:<feed_id>`; `feeds` rows carry `last_error_json`. It does not migrate or create a database. |
| `export` | writes a new directory | Produce immutable JSONL by publication window or changed-since cursor. Waits up to 90 seconds for the collector lock and holds it while reading. |
| `backup` | writes a new file | Use SQLite's online backup API; never copy a live WAL database directly. |
| `restore-check` | none | Read and integrity-check a backup without touching the live database. |
| `rebuild-articles` | database on apply | `--dry-run` compares the projection with retained sightings and reports differences overall and `by_source`. Apply takes the collector lock, reconciles the selected source in one transaction, and replaces its merge-state cache. Fails with `rebuild_unknown_feed`, `rebuild_invalid_sighting`, `rebuild_merge_state_mismatch`, or `rebuild_conflict` without changing the projection. |
| `deduplicate-sightings` | database on apply | `--dry-run` measures migration 005 savings on a read-only snapshot. `--backup PATH` takes the collector lock, writes and integrity-checks a new backup, then migrates a legacy database in one verified transaction. Already-migrated databases report `already_deduplicated`. |
| `benchmark-collect` | temporary files only | Compare unindexed, indexed, and cached ingestion on synthetic history in temporary databases. Never opens the configured database. |
| `capture-fixture` | network + two files | Fetch one configured feed plus a secret-free metadata sidecar. |
| `check` | caches only | Validate config, then run Ruff check, Ruff format check, compileall, offline pytest, and `sh -n` on the wrapper, each in a 300-second subprocess. No network. |
| `replay-payloads`, `live-contracts`, `enrich`, `snapshot-homepages` | none currently | Return explicit `disabled` results in release 1. Do not infer that work occurred. |

`--version` returns the normal JSON envelope. `--help` is the only human-readable stdout exception; each action's help ends with a realistic example, the top-level help does not.

## Collection

Always use one-shot collection:

```sh
./gather_news.sh collect --once --dry-run
./gather_news.sh collect --once
./gather_news.sh collect --source dr --once
```

The dry-run validates configuration and lists planned feeds without opening the database or making requests. The real run uses one non-waiting process lock. A second writer returns `error.type=lock_busy`; wait for the active run to finish, then retry once.

An individual feed failure is recorded while other feed transactions commit: the poll row becomes `failed` with the error, and `feed_state.consecutive_failures` increments. The `collect` result shows only the `succeeded`, `failed`, and `planned` counts; `ok=true` with `result.status=partial` is usable only with its stated coverage limitation. A total feed failure returns `ok=false` and `error.type=upstream_error`. Run `health` to see which feeds are failing: it lists every feed at or above the threshold under `reasons`, and a successful or `304` poll resets that feed's count.

Do not loop the command internally. The one-shot action runs every fifteen minutes under launchd from `editorial/config/launchd/ai.copenhagen-daily.collect.plist`; see `ingest/docs/scheduling.md`. Run from any directory; the wrapper changes to the repository itself.

## Export

Use exactly one mode:

```sh
./gather_news.sh export \
  --since 2026-09-07T00:00:00.000000Z \
  --until 2026-09-08T00:00:00.000000Z \
  --output exports/2026-09-07 --dry-run

./gather_news.sh export \
  --changed-since 2026-09-07T06:30:00.000000Z \
  --output exports/change-20260907T063000Z --dry-run
```

Publication windows use `since <= published_at < until`. Changed-since includes corrected or late-discovered older articles. The export takes the collector's process lock, waiting up to 90 seconds for a poll in flight, and holds it while it reads and stamps `generated_at`, so no concurrent poll can commit rows that fall behind that timestamp. After a successful incremental import, use the manifest's `generated_at` as the next inclusive cursor; tolerate boundary duplicates downstream so records are not missed. The exception is `rebuild-articles`: it restores each article's historical change time on purpose, so repairs it applies are not picked up by a changed-since export.

The parent directory must already exist and the target must not. Repeat without `--dry-run` only after checking the plan. Never delete or replace an old export to make a retry work.

## Backup and recovery

```sh
./gather_news.sh backup --output backups/news-20260907.sqlite3 --dry-run
./gather_news.sh backup --output backups/news-20260907.sqlite3
./gather_news.sh restore-check --backup backups/news-20260907.sqlite3
./gather_news.sh rebuild-articles --dry-run
```

Backups and restore checks are independent actions. A successful backup does not imply a restore check ran. Never use `cp` on the live database without its WAL files.

## Fixture capture

Capture only a configured first-party RSS feed, never an article body:

```sh
./gather_news.sh capture-fixture \
  --feed-id dr.latest \
  --output tests/fixtures/dr/latest.xml \
  --dry-run
```

The real call refuses to overwrite either the payload or its `.json` sidecar. The sidecar contains the feed/source identifiers, URLs, safe validator headers, capture time, byte count, and SHA-256. It must never contain cookies, authorization headers, credentials, or subscriber article bodies.

## Error handling

| `error.type` | Response |
|---|---|
| `invalid_arguments` | Read `details`, correct the named flag or value, and do not retry unchanged. |
| `resource_not_found` | Correct the path or perform the named prerequisite. |
| `conflict` | Choose a fresh immutable output path. |
| `permission_denied` | Fix the named file or directory permissions; do not retry unchanged. |
| `lock_busy` | Wait for the existing writer, then retry. |
| `timeout` | Retry once; repeated timeouts need diagnosis. |
| `upstream_error` | Check source health and retry only when transient. |
| `validation_failed` | Inspect the bounded stdout/stderr tails and fix the named check step. |
| `dependency_missing` | Ask the operator to provision `.venv` from the lockfile. Do not bypass the wrapper with a system Python. |
| `rebuild_unknown_feed` | A retained sighting references a feed absent from configuration (`details.feed_id`). Restore that feed's configuration, disabled if needed, and rerun. |
| `rebuild_invalid_sighting` | A retained sighting cannot produce a valid article (`details.sighting_id`). The projection is unchanged; investigate the sighting before retrying. |
| `rebuild_conflict` | An article with versions has no sightings. Apply refuses to delete it; investigate the missing evidence. |
| `rebuild_merge_state_mismatch` | The cached merge algorithm disagrees with full history for `details.source`/`source_id`. The projection is unchanged; treat as a defect to report. |
| `internal_error` | Retry once; if it repeats, report `details.exception` and inspect code/logs. |

The CLI is non-interactive. Never wait for a prompt, add a pager, or treat stderr as the machine result.
