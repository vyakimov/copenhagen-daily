# The collect slowdown

Status: index fix and metrics implemented, 29 September 2026, and measured live: the first scheduled
collect after migration 003 took 37 seconds (25 database, 11 fetch, 1 parse) against 31 minutes
before, inserting 3,103 sightings and reading 158,185 historical rows. Block 2 no longer depends on the poll's
speed (a run skips its own poll when the scheduled collector has polled within twenty minutes), so this
is a block 1 problem to fix on its own terms.

## What was observed

| When | `collect --once` wall time | How run |
|---|---|---|
| 24 September, first poll after three idle days | about 3 minutes | shell |
| 28 September, 14:21 | 17 minutes | launchd, `ProcessType: Background` (throttled) |
| 28 September, 14:44 | about 3.5 minutes | launchd, standard priority |
| 29 September, 09:00 | over 15 minutes, killed by block 2's budget | block 2 subprocess, while the scheduled collector was also running |
| 29 September, 11:16 | 31 minutes (2 minutes of user CPU, 9 of system) | shell, alone, `/usr/bin/time -l` |

The process spends most of its time in uninterruptible wait (state `U` in `ps`), that is, on disk, and
of its CPU time four fifths is system time, not user time. So this is I/O against the database, not
parsing or the network. The timed run also reported one feed failed of 132, which is unrelated.

## Where the bytes are

`var/news-ingest.sqlite3` is 2.2 GB. By `dbstat`:

| Table | Size | Rows |
|---|---|---|
| `sightings` | 1,722 MB | 218,158 |
| `article_versions` | 259 MB | |
| `articles` | 82 MB | 16,600 |
| `raw_payloads` | 63 MB (gzip) | 5,973 |
| `appearances` | 41 MB | 219,612 |

A sighting averages about 8 KB. A row that size carries the item's full text and metadata, and there
is one per item per poll: 132 feeds of roughly twenty items each is about 2,600 rows and 20 MB written
per poll, almost all of it identical to the previous poll's rows, since feed contents change slowly.
The raw payloads, which the design keeps forever, are not the problem: 63 MB compressed for the whole
history.

## Why it gets slower

Code inspection identified an unsupported lookup: for every identity in a successful feed response,
ingestion reads all sightings matching `(source, source_id)`. The existing unique index starts with
`feed_id`, so this produced `SCAN sightings`, potentially thousands of full-table scans per run.
Collection already limits projection work to affected identities and inserts only current
appearances; it does not rebuild all articles or refresh historical appearances.

Even with the new index, historical rows read and deserialized per affected identity grow with
retained observations. Continuous operation increases history; a fifteen-minute cadence alone grows
it more slowly than a five-minute cadence. Phase timings are needed to distinguish database,
parsing, and network costs rather than inferring their proportions from process state alone.

## Implemented first step

- Migration 003 adds `sightings_article_idx(source, source_id)`. Lookup now uses an indexed search.
  Explicit sighting-ID ordering and sorted identity processing keep merge ordering deterministic.
- Collection reports fetch, parse, database, and total seconds, committed sightings inserted, and
  historical rows read. The README defines timing boundaries and counter semantics.
- `./gather_news.sh benchmark-collect` compares identical disposable synthetic histories: 10,000
  sightings, 500 identities, and a new 20-item response. The first local result was 0.228252 seconds
  unindexed versus 0.024760 seconds indexed (about 9×), with identical article projections and 420
  historical rows read in each case. This is not a live workload estimate.
- Offline checks and temporary-database CLI tests cover successful, failed, partial, rolled-back,
  and `304` responses. No production collection was started for verification.

## Remaining work, in order

1. **Keep observing scheduled collections.** The first post-migration poll is above; watch the
   database phase and `historical_rows_read` over the coming days, since both still grow with history.
2. **Measured live, 29 September afternoon.** The bootstrap poll initialised 3,010 identities from
   144,775 history rows in 19.7 seconds of database time; the next poll read 3,256 history rows for
   3,156 sightings inserted, 14 bootstraps for new articles, and spent 3.0 seconds in the database of
   26.7 in total. The database phase is no longer the cost; fetch is. **Observe the implemented persistent merge state.** Migration 004 caches per-article/per-feed
   field winners and aggregates. The first observation initializes an article from history; later
   polls read only new sightings after its watermark. Monitor `merge_state_bootstraps`,
   `merge_state_rows_read`, and `historical_rows_read`. All history remains retained. The offline
   20-item trial read 20 sightings with a warm cache versus 420 during indexed initialization,
   taking 0.013486 versus 0.024541 seconds with identical projections. This is not a live estimate.
3. **Use the implemented rebuild as a correctness reference.** `rebuild-articles` now reconstructs
   from retained sightings, previews differences by source, and repairs atomically while preserving
   versions. Its shared streaming merge accumulator avoids merging every historical prefix from
   scratch. It also checks the per-feed cache algorithm against the full-history result and refreshes
   caches on apply. See `operations.md` for validation, locking, and missing-evidence behavior.
4. **Implemented: lossless content deduplication; live rollout pending.** Migration 005 shares
   exact normalized content and raw JSON using a separate storage digest, not article `content_hash`.
   Every observation, placement, ID, and timestamp is retained. Tests cover byte-exact reconstruction,
   `A -> B -> A`, collision rejection, and transactional rollback. Populated databases remain on the
   legacy layout until an explicit `deduplicate-sightings --backup NEW_PATH`; the collector supports
   both layouts. See the rehearsal below and `operations.md` before applying.
5. **Reclaim space after migration validation.** Schedule compaction with sufficient disk headroom.
   Measure WAL/checkpoint behavior before adding mandatory per-collection checkpoints.

### Deduplication rehearsal, 29 September after 16:30

Applied only to an isolated SQLite backup, not the live database:

- 282,801 sightings shared 29,056 distinct content records. Repeated JSON occupied 2,033,688,116
  bytes; shared content plus observation timestamp literals occupied 250,128,110 bytes, saving
  1,783,560,006 bytes (87.7%). These are payload bytes, not a final database-size estimate.
- Migration verified the full reconstructed sighting history against a before-migration SHA-256
  fingerprint within the transaction. SQLite integrity checks passed, and full-window exports of
  17,006 articles and 284,825 appearances had identical file hashes before and after.
- Full rebuild previews before and after both reported the same 463 existing projection differences:
  Borsen 133, DR 237, FT 81, Politiken 12; no additions or removals. These need separate investigation;
  deduplication neither introduced nor repaired them.
- No VACUUM was performed. The migrated copy allocated 3,254,468,608 bytes, of which 2,293,030,912
  were free pages reusable by SQLite. Returning those pages to the filesystem is a separate,
  explicitly scheduled maintenance operation.

## What not to do

Do not shorten retention of raw payloads to fix this; they are small and they are the audit trail. Do
not move the database off SQLite; the table design, not the engine, is the cause. Do not lengthen the
poll interval as a fix; fifteen minutes is the right cadence for ten-item feeds, and the schedule
should not bend to a storage defect.

## Interim state

The collector runs every fifteen minutes under launchd. Overlapping polls fail fast on the process lock
and are harmless. Block 2's morning run uses the last completed poll rather than starting one, so the
paper avoids that synchronous collection delay. Freshness depends on the last successful completed
collection; a fifteen-minute schedule does not guarantee a fifteen-minute freshness bound.
