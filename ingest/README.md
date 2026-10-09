# news-ingest

`news-ingest` is a small, portable Python service that records every valid item observed in configured first-party RSS feeds from NYT, FT, Børsen, Politiken, Berlingske, DR, TV 2, Jyllands-Posten, Information, Altinget, Kristeligt Dagblad, BBC News, The Economist, The Guardian, The Washington Post, and The Wall Street Journal. It stores raw feed payloads, feed sightings, and a rebuildable article projection, then atomically exports deterministic JSONL bundles.

It also collects third-party press releases and announcements distributed by
Via Ritzau (`via_ritzau`) from its latest-releases RSS feed. This source represents
the distribution service, not Ritzau's editorial newswire or the original sender.

It is metadata-only in release 1. It does not use an LLM, a browser, login automation, subscription cookies, paywall bypasses, page crawling, ranking, summaries, or cross-publisher clustering. Coverage means items observed while polling the configured feeds; feeds have finite windows and cannot prove that an item absent between polls was collected.

Every exported appearance includes a source-local publisher-prominence score in
the range 0–1, its `high`/`medium`/`low` tier, the evidence surface, and the
snapshot item count. Homepage RSS rank is strong evidence; latest and section
feed ranks have lower score ceilings and must not be described as visual
homepage placement.

Each exported article also has a nullable `publisher_prominence` object holding
its strongest observed placement signal. `appearances.jsonl` retains the full
history and evidence behind that summary.

## Quick start

The operator must provision `.venv` from the committed `uv.lock` once. After
that, use the repository's single allowlist-friendly entrypoint for every
workflow; it locates the repository and virtual environment itself and always
returns a JSON envelope.

```sh
./gather_news.sh list-actions
./gather_news.sh validate-config
./gather_news.sh collect --once --dry-run
./gather_news.sh collect --once
./gather_news.sh health
./gather_news.sh rebuild-articles --dry-run
./gather_news.sh export --since 2026-01-01T00:00:00.000000Z --until 2027-01-01T00:00:00.000000Z --output exports/initial --dry-run
```

Repeat a mutating command without `--dry-run` only after reviewing its plan.
Use `./gather_news.sh check` for the complete offline repository verification.

`health` returns `status: degraded` and a `feed_failures:<feed_id>` reason for
every feed whose `consecutive_failures` has reached `failure_alert_threshold`
(3 in `config/sources.yaml`). A failed poll increments that counter and stores
the error in `feed_state.last_error_json`; a successful or `304` poll resets it
to 0.

`export` takes the collector's process lock, waiting up to 90 seconds for a
poll in flight, and holds it while it reads and stamps `generated_at`. A
changed-since cursor taken from the manifest therefore cannot fall behind rows
a concurrent poll commits. The one exception is `rebuild-articles`, which
restores each article's historical change time on purpose, so repairs it
applies are not visible to a changed-since export.

The project-local agent skill is
[`skills/news-ingest/SKILL.md`](../skills/news-ingest/SKILL.md) at the repository root. Its short main
file covers daily use; optional references hold operations, development, and
data-contract details.

See `docs/operations.md` and `docs/scheduling.md` for operations and scheduling.

## Collection performance

`collect --once` returns `timings_seconds` (`fetch`, `parse`, `database`, and
`total`), `sightings_inserted`, `historical_rows_read`, `merge_state_rows_read`,
and `merge_state_bootstraps`, also saved in the
fetch-run summary. Times use a monotonic clock. Database time includes startup,
migrations, poll allocation, feed transactions, and failure recording. Total runs
from collection entry until summary construction, excluding the final summary
commit and connection close. Fetch includes retries and client setup. Counters
include only committed successful `200` feeds; historical rows include the current
poll's new sightings. Failed transactions contribute time but no counters, and
`304` responses contribute no sighting rows.

Migration 003 automatically adds the article-identity lookup index on the next
collection. Its first creation can take extra time and disk space. Subsequent
collections use migration 004's persistent per-article/per-feed merge state.
Each article's first post-upgrade observation initializes its state from retained
history. Later observations read only sightings after its saved watermark, plus
one cache row per contributing feed. The cache and watermark commit atomically
with the feed's sightings, projection, versions, and validators.

`historical_rows_read` counts normalized sightings actually read, including current
observations; it should approach `sightings_inserted` after initialization.
`merge_state_rows_read` counts loaded per-feed cache rows, and
`merge_state_bootstraps` counts identities initialized or recovered from history
(including brand-new articles). `rebuild-articles` replays full history, checks
that the persisted cache reproduces it, and refreshes the selected cache on apply.

```sh
./gather_news.sh benchmark-collect
```

This network-free comparison builds 10,000 synthetic sightings in temporary
databases, ingests the same 20-item RSS response without the index, with the index
and a cold cache, and with the index and a warm cache,
reports query plans and elapsed times, and checks identical article projections.
Temporary files are removed on completion; the configured database is never
opened. The temporary databases use the migration 005 layout and take tens of
megabytes. Cache warm-up is outside the timed warm-cache trial. Timings are diagnostic,
not a test threshold or a prediction of live collection speed.

## Sighting content deduplication

Migration 005 stores repeated content once while retaining every observation and
its original JSON text. New databases apply it automatically. A populated
database takes it only through the explicit command below; the live database
was migrated this way and vacuumed on 30 September 2026, so the command is now
relevant for a restored legacy backup:

```sh
./gather_news.sh deduplicate-sightings --dry-run
./gather_news.sh deduplicate-sightings --backup var/pre-dedup-YYYY-MM-DD.sqlite3
```

Apply holds the process lock, creates and integrity-checks a new backup, and verifies
exact reconstruction of every sighting before committing the migration. It does
not rebuild articles, alter versions, or run `VACUUM`. The dry-run reports JSON
savings separately from database page allocation/free space. See
[`docs/operations.md`](docs/operations.md) for migration and recovery details.

## History compaction

Polling records every item in every feed each time, so most of what accumulates
repeats the previous poll. `compact-history`, run daily under launchd, archives
raw payloads older than `compact_after_days` into verified xz archives and folds
unbroken runs of identical old sightings and appearances to their first and last
rows. Rebuilds and exports are unchanged by it:

```sh
./gather_news.sh compact-history --dry-run
./gather_news.sh compact-history
```

See [`docs/operations.md`](docs/operations.md) ("History compaction").
