# Data and source contracts

Read this file when changing normalization, identity, persistence, collection, prominence, exports, replay, or source configuration.

## Fact and projection model

Persist every valid observed feed item, including old items and duplicates across feeds. Raw compressed payloads and sightings are immutable facts. `articles` is the deterministic current projection; `article_versions` records every actual content transition, including `A -> B -> A` as three versions. Observation-only changes never create a content version.

Identity never crosses publishers. Preserve `(source, source_id)` in all downstream work. Preserve publisher input exactly in `raw_url`; remove tracking/fragment material only in `canonical_url` according to the configured rules.

Timestamps are UTC RFC 3339 text with six fractional digits and `Z`. Feed publication timestamps need an explicit offset; do not infer one from collection time or a URL.

## Source rules

| Source | Identity | Essential behavior |
|---|---|---|
| NYT | Nonempty RSS GUID | Preserve one-based placement and standout metadata. Never fetch article pages. |
| FT | Canonical lowercase UUID GUID | Remove dynamic `syn-*` only from canonical URLs. Homepage RSS rank is strong; section order is weak. |
| Børsen | Nonempty GUID, canonical URL fallback | Keep main/category sightings. Short URL aliases need real canonical resolution before non-RSS deduplication. |
| Politiken | First `art([0-9]+)` URL match, GUID fallback | Keep `pol:order` separate from XML position. Optional homepage HTML remains gated. |
| Berlingske | Complete `urn:bm:article:<uuid>` GUID | Remove `referrer=RSS` only from canonical URLs. Keep all-news and main-section sightings. |
| DR | Complete GUID URN | Section descriptions outrank latest-feed descriptions via configured priority. Preserve `focusId`. |

Do not add authenticated page access, browser automation, cookies, paywall bypasses, archive crawling, or historical completeness claims. HTML homepage placement and public article enrichment remain disabled until their explicit plan gates are met and the user approves the expanded scope.

## Transaction rules

Use one transaction for each successful HTTP `200` response. That transaction stores the payload, sightings, quarantine records, affected projections and versions, appearances, final poll state, and validators. If parsing or database work makes the feed unusable, roll it all back, then record only the failed poll/state in a short separate transaction.

A valid `304` updates poll/check state but creates no payload, sighting, version, or appearance. HTTP validators may advance only with successfully parsed and committed data, with that `304` exception.

Every database-mutating command uses the non-waiting process lock. Never rely on HTTP completion order or SQLite default row order. Keep SQL inside `db.py` and use explicit ordering for merging and output.

## Prominence

Prominence describes an observation, not article content, and never affects `content_hash`. Normalize rank by the number of items in that snapshot. Evidence ceilings are `1.0` for homepage/homepage RSS, `0.65` for latest RSS, and `0.50` for section RSS. Scores at least `0.75` are high, at least `0.40` medium, and lower scores low.

Prefer Politiken's explicit publisher order when present while retaining both values. Every exported appearance includes snapshot item count, score, tier, and precise evidence. Describe what RSS proves—such as “ranked first in the FT International Homepage RSS snapshot”—rather than claiming visual homepage treatment.

## Export and recovery

Exports are schema-validated, deterministic, immutable, and atomically published. Article ordering is publication time, source, source ID. Appearance ordering is observation time, source, source ID, surface ID, position. Include nullable fields explicitly and validate hashes/counts before exposing the target directory.

Publication-window exports select `since <= published_at < until`. Changed-since exports capture late discoveries and corrections regardless of article age. Preserve the complete configured feed set and honest coverage gaps in metadata, including when collection used `--source`.

Never overwrite an export directory or backup. Use SQLite's backup API rather than copying a live main file without WAL files. Rebuilds must not rewrite sightings or append article versions. Replay is diagnostic unless a separately reviewed apply plan is approved.

## Tests for contract changes

Use saved, secret-free fixtures and table-driven cases. Freeze clocks, retry sleeps, and jitter; tests never sleep. Add regression coverage for identity, tracking cleanup, timestamp parsing, description precedence, unchanged repetitions, `A -> B -> A`, failed feed rollback, `304`, publisher isolation, deterministic ordering, export atomicity, and structured error codes as relevant to the change.

Network-backed checks belong under `tests/live/`, marked `live`, and never run in `./gather_news.sh check`. A publisher outage is not an offline test failure.
