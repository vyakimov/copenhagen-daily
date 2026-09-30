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
| TV 2 | Permalink GUID | One latest-news feed at `feeds.services.tv2.dk`; query parameters are ignored, so no section feeds. |
| Jyllands-Posten | First `ECE([0-9]+)` URL match, GUID fallback | `topnyheder` is an editorially ordered homepage surface; `seneste` is latest-news evidence. Both aliases redirect to a publisher-owned proxy and carry ten items. |
| Information | Drupal GUID (`<node id> at https://www.information.dk`) | Single site-wide latest feed. |
| Altinget | URL GUID | Front feed is latest-news evidence; `/<section>/rss` feeds are weaker section evidence. |
| Kristeligt Dagblad | UUID GUID | `pubDate` is ISO 8601; timestamp parsing accepts ISO 8601 after RFC 2822. |
| Via Ritzau | Complete GUID URL | Third-party press releases from the distribution service, not Ritzau's newswire. `latest_rss` placement; do not assume Danish from `lang=da`. |
| BBC | Article id from `/articles/<id>`, `/videos/<id>`, `/live/<id>`, GUID fallback | GUIDs carry a per-feed `#N` fragment that would split identities. The top-stories feed is a ranked homepage surface. |
| The Economist | UUID GUID | Every feed carries 300 items. |
| The Guardian | GUID (URL) | The international feed is a ranked homepage surface. |
| The Washington Post | GUID (URL) | Small section feeds only. |
| The Wall Street Journal | GUID (`WP-WSJ-...`) | Feeds live at `feeds.content.dowjones.io`; the `feeds.a.dj.com` aliases are stale. |

A publisher may list the same article twice in one feed snapshot (BBC and WSJ do). The first placement is the sighting; later repeats are written to `quarantine` with `error_code` `duplicate_in_snapshot`, and the poll still succeeds. Weekendavisen, Zetland, Reuters, and the Associated Press publish no usable first-party RSS and are not monitored.

Do not add authenticated page access, browser automation, cookies, paywall bypasses, archive crawling, or historical completeness claims. HTML homepage placement and public article enrichment remain disabled until their explicit plan gates are met and the user approves the expanded scope.

## Transaction rules

Use one transaction for each successful HTTP `200` response. That transaction stores the payload, sightings and their shared `sighting_contents` rows, quarantine records, the per-feed merge-state cache (`article_feed_merge_state` and `article_merge_heads`, migration 004), affected projections and versions, appearances, final poll state, and validators. If parsing or database work makes the feed unusable, roll it all back, then record the failure in a short separate transaction: the poll row becomes `failed` with `error_json`, and `feed_state.consecutive_failures` increments with `last_error_json` set. `health` reports the feed once the count reaches `failure_alert_threshold`; a later `200` or `304` resets it to 0.

A valid `304` marks the poll `not_modified`, updates `last_checked_at` and `last_successful_poll_at`, and resets the failure count. It creates no payload, sighting, version, or appearance, does not touch merge state, and leaves the stored ETag and Last-Modified validators unchanged. Validators advance only inside a committed `200` transaction.

Every database-mutating command uses the non-waiting process lock. Never rely on HTTP completion order or SQLite default row order. Keep SQL inside `db.py` and use explicit ordering for merging and output.

## Prominence

Prominence describes an observation, not article content, and never affects `content_hash`. Normalize rank by the number of items in that snapshot. Evidence ceilings are `1.0` for homepage/homepage RSS, `0.65` for latest RSS, and `0.50` for section RSS. Scores at least `0.75` are high, at least `0.40` medium, and lower scores low.

Prefer Politiken's explicit publisher order when present while retaining both values. Every exported appearance includes snapshot item count, score, tier, and precise evidence. Describe what RSS proves, such as "ranked first in the FT International Homepage RSS snapshot", rather than claiming visual homepage treatment.

## Export and recovery

Exports are schema-validated, deterministic, immutable, and atomically published. Article ordering is publication time, source, source ID. Appearance ordering is observation time, source, source ID, surface ID, position. Include nullable fields explicitly. The bundle is written to a staging directory beside the target; each JSONL file's SHA-256 and byte count and the record counts are written into `manifest.json`, and the directory is then renamed into place. Nothing is validated against the manifest before the rename.

Publication-window exports select `since <= published_at < until`. Changed-since exports select `last_changed_at >= cursor` and so capture late discoveries and corrections regardless of article age. The export holds the collector's process lock (waiting up to 90 seconds for a poll in flight) while it reads and stamps `generated_at`, so that timestamp is a safe next cursor. The exception is `rebuild-articles`, which restores each article's historical change time on purpose; repairs it applies are not visible to a changed-since export.

The manifest holds `schema_version`, `generated_at`, `export_mode`, `window` or `changed_since`, `article_count`, `appearance_count`, `files`, and empty `coverage_gaps` and `warnings` lists. It does not record the configured feed set or whether collection used `--source`.

Never overwrite an export directory or backup. Use SQLite's backup API rather than copying a live main file without WAL files. Rebuilds must not rewrite sightings or append article versions. `replay-payloads` is disabled and returns `status: disabled`; `rebuild-articles` from retained sightings is the only repair path.

## Tests for contract changes

Use saved, secret-free fixtures and table-driven cases. Freeze clocks, retry sleeps, and jitter; tests never sleep. Add regression coverage for identity, tracking cleanup, timestamp parsing, description precedence, unchanged repetitions, `A -> B -> A`, failed feed rollback, `304`, publisher isolation, deterministic ordering, export atomicity, and structured error codes as relevant to the change.

Any network-backed test must carry the `live` marker registered in `pyproject.toml`; `./gather_news.sh check` runs `pytest -m "not live"`. No live tests exist today. A publisher outage is not an offline test failure.
