# The collect slowdown

Status: diagnosis, 29 September 2026. Nothing here is built. Block 2 no longer depends on the poll's
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

Two things grow with every poll. The `sightings` table grows by the full content of every item seen,
whether or not it changed, so writes and the indexes over them get heavier. And whatever the collect
does over all sightings on each run, the projection rebuild and the appearance refresh being the
candidates, scans a table that is now nearly two gigabytes. Fifteen-minute polls make both curves
steeper than the five-minute schedule the plan assumed, because idle days no longer thin the history.
Left alone, a poll will exceed its own interval within weeks.

## Proposed fixes, in order of payoff

1. **Store sighting content once, by content hash.** Split `sightings` into a content table keyed by
   `content_hash` (title, description, metadata, everything that is a property of the item) and a
   thin sighting table of `(poll_id, feed_id, content_hash, position, observed_at)`. An item seen a
   hundred times is stored once and referenced a hundred times. Expected size: tens of megabytes rather
   than gigabytes. This is the change that matters; the rest are minor next to it. It needs a
   forward-only migration and a rebuild of the projection from the migrated tables, and it keeps the
   invariant that sightings are facts and `articles` is a projection.
2. **Make the projection incremental.** Rebuild only articles whose content hash or placement changed
   in this poll, keyed off the poll's own sightings, rather than scanning history. The full rebuild
   stays available as `rebuild-articles`.
3. **Checkpoint and vacuum.** After the migration, `VACUUM` to return the space, and confirm the WAL is
   checkpointed on each collect so it does not grow between polls.
4. **Measure before and after.** Add the poll's wall time and rows written to the `collect` envelope,
   so the next slowdown is visible in the logs instead of in a missed edition.

## What not to do

Do not shorten retention of raw payloads to fix this; they are small and they are the audit trail. Do
not move the database off SQLite; the table design, not the engine, is the cause. Do not lengthen the
poll interval as a fix; fifteen minutes is the right cadence for ten-item feeds, and the schedule
should not bend to a storage defect.

## Interim state

The collector runs every fifteen minutes under launchd. Overlapping polls fail fast on the process lock
and are harmless. Block 2's morning run uses the last completed poll rather than starting one, so the
paper is at most fifteen minutes behind the feeds and is not delayed by this.
