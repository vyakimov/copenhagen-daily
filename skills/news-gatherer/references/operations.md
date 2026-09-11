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
| `health` | none | Read SQLite integrity and feed failure state. It does not migrate or create a database. |
| `export` | writes a new directory | Produce immutable JSONL by publication window or changed-since cursor. |
| `backup` | writes a new file | Use SQLite's online backup API; never copy a live WAL database directly. |
| `restore-check` | none | Read and integrity-check a backup without touching the live database. |
| `rebuild-articles` | potentially database | Compare with `--dry-run` first. The current release exposes conservative projection behavior. |
| `capture-fixture` | network + two files | Fetch one configured feed plus a secret-free metadata sidecar. |
| `check` | caches only | Run Ruff, formatting, compilation, offline tests, and config validation without network. |
| `replay-payloads`, `live-contracts`, `enrich`, `snapshot-homepages` | none currently | Return explicit `disabled` results in release 1. Do not infer that work occurred. |

`--version` returns the normal JSON envelope. `--help` is the only human-readable stdout exception and includes a realistic example.

## Collection

Always use one-shot collection:

```sh
./gather_news.sh collect --once --dry-run
./gather_news.sh collect --once
./gather_news.sh collect --source dr --once
```

The dry-run validates configuration and lists planned feeds without opening the database or making requests. The real run uses one non-waiting process lock. A second writer returns `error.type=lock_busy`; wait for the active run to finish, then retry once.

An individual feed failure remains visible while other feed transactions commit. `ok=true` with `result.status=partial` is usable only with its stated coverage limitation. A total feed failure returns `ok=false` and `error.type=upstream_error`. Run `health` to inspect persistent feed state.

Do not loop the command internally. Schedule the one-shot action every five minutes using the absolute wrapper path. Run from any directory; the wrapper changes to the repository itself.

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

Publication windows use `since <= published_at < until`. Changed-since includes corrected or late-discovered older articles. After a successful incremental import, use the export manifest's generation boundary as the next inclusive cursor; tolerate boundary duplicates downstream so records are not missed.

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
| `lock_busy` | Wait for the existing writer, then retry. |
| `timeout` | Retry once; repeated timeouts need diagnosis. |
| `upstream_error` | Check source health and retry only when transient. |
| `validation_failed` | Inspect the bounded stdout/stderr tails and fix the named check step. |
| `dependency_missing` | Ask the operator to provision `.venv` from the lockfile. Do not bypass the wrapper with a system Python. |
| `internal_error` | Retry once; if it repeats, report `details.exception` and inspect code/logs. |

The CLI is non-interactive. Never wait for a prompt, add a pager, or treat stderr as the machine result.
