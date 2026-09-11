# Detailed implementation plan: portable RSS news ingestion

## 1. How to use this plan

This is the execution plan for block 1, which lives in `ingest/` of the `copenhagen-today`
repository (relocated there on 11 September 2026; paths below are relative to `ingest/`). It expands the Obsidian note
`Inbox/Programmatic news ingestion plan — NYT, Politiken, Børsen, and DR.md` and adds the
Financial Times (FT) and Berlingske to the source scope.

Implement the work packages in order. Do not start an optional work package until its gate is
met. Each package names the files to create, the behavior to implement, the tests to add, and the
condition that makes the package complete. If a detail in the source note and this plan appears to
conflict, preserve these invariants:

1. Ingestion is deterministic and contains no LLM calls.
2. First-party RSS is the primary source of truth.
3. Every valid observed feed item is persisted, even when it is old or duplicated across feeds.
4. Raw payloads and sightings are facts; the `articles` table is a rebuildable projection.
5. HTTP validators advance only in the same transaction as successfully parsed data.
6. Publisher failures are isolated and visible.
7. Export bundles are schema-validated, deterministic, and published atomically.
8. No browser, login automation, paywall bypass, anti-bot evasion, or subscriber-cookie handling is
   part of this project.

The first release ends after Work Package 13 and the 48-hour soak test. Work Packages 14 and 15
are optional follow-ups.

## 2. Product boundary

Build a Python 3.12 service and CLI named `news-ingest`. It polls configured first-party feeds from
NYT, FT, Børsen, Politiken, Berlingske, and DR; normalizes and versions every valid item; records feed placement;
and publishes JSONL bundles for a separate briefing agent.

“Complete” means every item observed in the enabled feeds while the collector is running. It does
not mean every article published by each publisher. Feeds have finite windows, and the system must
state that limitation in its README, health output, and export manifest.

The collector must not select stories, score relevance, summarize or rewrite articles, cluster a
story across publishers, generate briefing Markdown, crawl archives, or fetch subscriber-only text.

### Source policy for release 1

| Source | Stable identity | Release 1 acquisition | Placement signal | Page extraction |
|---|---|---|---|---|
| NYT | RSS GUID | International/HomePage RSS | One-based feed order plus `rel="standout"` | Permanently disabled; non-browser clients are DataDome-blocked |
| FT | RSS GUID UUID | International homepage RSS plus configured section RSS feeds | Homepage feed order is the main prominence signal; section feed order is a weak section signal | Disabled; no subscription credentials or cookies are used |
| Børsen | RSS GUID | Main feed plus all enabled category feeds | Main-feed order | Disabled by default |
| Politiken | `art([0-9]+)` from URL, GUID fallback | Latest-news RSS | `pol:order` and XML position; optional HTML homepage later | Disabled by default |
| Berlingske | Complete RSS GUID URN | All-news RSS plus four main category feeds | Latest-feed and weaker section-feed order | Disabled by default |
| DR | Full RSS GUID URN | Latest plus all enabled section and regional feeds | Feed membership and XML position | Disabled by default |

FT was verified on 2026-09-07 using plain HTTP. The international homepage feed is
`https://www.ft.com/rss/home/international`. It contains an ordered ten-item homepage snapshot,
has `ttl=15`, and supplies title, description, link, a non-permalink UUID GUID, timezone-aware GMT
`pubDate`, and `media:thumbnail`. The response supports ETag-based caching. The following section
URLs returned 25-item RSS documents on that date:

- `https://www.ft.com/world?format=rss`
- `https://www.ft.com/global-economy?format=rss`
- `https://www.ft.com/companies?format=rss`
- `https://www.ft.com/markets?format=rss`
- `https://www.ft.com/technology?format=rss`
- `https://www.ft.com/climate-capital?format=rss`
- `https://www.ft.com/opinion?format=rss`
- `https://www.ft.com/work-careers?format=rss`
- `https://www.ft.com/life-arts?format=rss`

The FT article URL seen in the feed contains a changing tracking parameter shaped like
`syn-<hex>=1`. Preserve it in `raw_url`, remove it from `canonical_url`, and use the GUID rather
than either URL as identity. Treat the homepage feed as an observed international homepage, not a
claim about every regional FT homepage. Keep the feed URL configurable.

Berlingske was verified on 2026-09-08 using plain HTTP. The public
`https://www.berlingske.dk/content/rss` alias redirects to the publisher-owned
`/next-api/feeds/alle` RSS endpoint, returns ten recent items, and supplies title, description,
link, a complete non-permalink `urn:bm:article:<uuid>` GUID, timezone-aware GMT `pubDate`, optional
author and category values, and an optional image enclosure. The configured Samfund, Business,
Kultur, and Opinion aliases redirect to equivalent category feeds. Preserve the feed-provided
`referrer=RSS` query in `raw_url`, remove it from `canonical_url`, and use the full GUID as identity.

## 3. Locked technical decisions

- Python 3.12 and a `src/` package layout.
- `uv` manages the environment and a committed `uv.lock`.
- Runtime libraries: `httpx`, `feedparser`, `pydantic`, `PyYAML`, and `selectolax` (the last one is
  unused until optional HTML work begins).
- Test libraries: `pytest`, `pytest-asyncio`, and `respx`.
- Use the standard library for SQLite, argparse, gzip, hashing, JSON, logging, time zones, and the
  process lock. Use `fcntl.flock` on the deployment host and fail validation on unsupported
  platforms rather than silently running unlocked.
- Store all timestamps as UTC RFC 3339 text with six fractional digits and a trailing `Z`.
- Use `zoneinfo.ZoneInfo("Europe/Copenhagen")` only when an optional page timestamp is known to be
  Danish local time but has no offset. Feed timestamps without an offset are invalid.
- Use one `httpx.AsyncClient` per collection run, HTTP/2 enabled, redirects enabled, and at most two
  connections per host.
- Use SQLite WAL mode, foreign keys, a busy timeout, explicit migrations, and one transaction per
  feed response.
- Do not create a module per publisher. Feed behavior belongs in `config/sources.yaml`; only stable
  identity/URL policies and optional HTML extractors may contain source-specific branches.
- JSON on stdout is the CLI contract. Human diagnostics and structured logs go to stderr.
- The block directory is `ingest/`; the import package and command remain
  `news_ingest` and `news-ingest`.

Do not invent dependency versions in advance. Resolve once with `uv`, copy each resolved direct
dependency version into an exact `==` pin in `pyproject.toml`, regenerate `uv.lock`, and commit both.
The lockfile pins transitive dependencies.

## 4. Target repository layout

Create this layout. Do not add a service framework, ORM, task queue, web UI, or publisher adapter
hierarchy.

```text
.
├── .gitignore
├── README.md
├── pyproject.toml
├── uv.lock
├── config/
│   └── sources.yaml
├── docs/
│   ├── operations.md
│   ├── scheduling.md
│   └── source-contracts.md
├── migrations/
│   └── 001_initial.sql
├── src/news_ingest/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── time.py
│   ├── urls.py
│   ├── identity.py
│   ├── hashing.py
│   ├── http.py
│   ├── feed.py
│   ├── merge.py
│   ├── db.py
│   ├── collect.py
│   ├── export.py
│   ├── health.py
│   ├── replay.py
│   ├── article_enrichment.py
│   └── homepage.py
├── tools/
│   └── capture_fixture.py
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── manifest.json
    │   ├── nytimes/
    │   ├── ft/
    │   ├── borsen/
    │   ├── politiken/
    │   └── dr/
    ├── test_config.py
    ├── test_time.py
    ├── test_urls.py
    ├── test_identity.py
    ├── test_feed.py
    ├── test_http.py
    ├── test_merge.py
    ├── test_db.py
    ├── test_collect.py
    ├── test_replay.py
    ├── test_export.py
    ├── test_health.py
    ├── test_enrichment.py
    ├── test_homepage.py
    └── live/
        └── test_source_contracts.py
```

## 5. Public data contracts

Put all boundary models in `src/news_ingest/models.py`. Configure Pydantic to reject unknown
fields on configuration and internal command models. Export models must emit every nullable field
as `null` and must use `schema_version=1`.

### `ArticleSnapshot`

Use these fields and types. The “hashed” column determines whether the field participates in
`content_hash` and version creation.

| Field | Type | Required | Hashed | Rule |
|---|---|---:|---:|---|
| `schema_version` | literal `1` | yes | yes | Always 1 |
| `source` | enum/string | yes | yes | One of the enabled source IDs |
| `source_id` | nonempty string | yes | yes | Result of the configured identity policy |
| `content_type` | string | yes | yes | Default `article`; preserve known DR reel/live values |
| `title` | nonempty string | yes | yes | Unicode-normalized and whitespace-collapsed |
| `raw_url` | absolute HTTP(S) URL | yes | no | Exact publisher URL from the selected sighting |
| `canonical_url` | URL or null | yes | yes | Tracking removed; null only when no valid URL exists |
| `description` | string or null | yes | yes | Clean text, not raw HTML |
| `description_source` | string or null | yes | yes | Feed ID or later `html_meta`/`json_ld` |
| `public_lead` | string or null | yes | yes | Null in release 1 |
| `public_body` | string or null | yes | yes | Null in release 1 |
| `public_body_truncated` | boolean | yes | yes | False in release 1 |
| `language` | string or null | yes | yes | `en` for NYT/FT; `da` for the Danish publishers unless feed declares otherwise |
| `authors` | list of strings | yes | yes | Empty list allowed |
| `categories` | list of strings | yes | yes | Sorted, de-duplicated |
| `keywords` | list of strings | yes | yes | Sorted, de-duplicated |
| `image_url` | URL or null | yes | yes | Prefer first valid source image |
| `image_credit` | string or null | yes | yes | Preserve NYT value when present |
| `image_description` | string or null | yes | yes | Preserve NYT value when present |
| `published_at` | UTC datetime | yes | yes | Parsed from RSS `pubDate` only |
| `modified_at` | UTC datetime or null | yes | yes | Null in release 1 |
| `timestamp_original` | string | yes | yes | Exact RSS source string |
| `timestamp_assumed_timezone` | boolean | yes | yes | False for all valid release 1 feed records |
| `first_seen_at` | UTC datetime | yes | no | Earliest committed sighting |
| `last_seen_at` | UTC datetime | yes | no | Latest parsed response containing the item |
| `last_checked_at` | UTC datetime | yes | no | Latest check of any feed supplying the current article |
| `access_status` | enum | yes | yes | `metadata_only` for NYT/FT; otherwise `unknown` in release 1 |
| `content_hash` | `sha256:<hex>` | yes | n/a | Calculated after all hashed fields are finalized |
| `raw_metadata` | JSON object | yes | no | JSON-safe complete `feedparser` entry from the chosen latest sighting |

Access status is one of `open`, `partial`, `metadata_only`, `blocked`, or `unknown`.

### `AppearanceRecord`

Required fields:

- `schema_version: 1`
- `poll_id: int`
- `source: str`
- `source_id: str`
- `surface_id: str` (stable configured feed ID or homepage ID)
- `surface: str` (`homepage_rss`, `latest_rss`, `section_rss`, or `homepage`)
- `surface_section: str | null`
- `position: int` (one-based parsed item/document order)
- `publisher_order: int | null` (Politiken `pol:order`, kept separately)
- `is_super_article: bool | null` (only optional Politiken homepage work populates this)
- `observed_at: datetime`

A `304` creates no appearance row. Every valid item in a parsed `200` response does.

### `ExportManifest`

Required fields:

- `schema_version`, `generated_at`, and `export_mode` (`publication_window` or `changed_since`)
- Exactly one boundary object: `window: {since, until}` or `changed_since`
- `article_count`, `appearance_count`, and counts per source
- SHA-256 and byte count for each emitted file
- `config_hash` over canonicalized, secret-free configuration
- Ordered list of enabled feed IDs
- Per-feed last check, last success, consecutive failures, last item count, and newest publication
- Quarantine counts by source/feed since the export boundary
- Explicit `coverage_gaps` and `warnings` arrays (empty arrays are valid only after checks run)

## 6. Configuration contract

Implement configuration models in `config.py` and load `config/sources.yaml` with `yaml.safe_load`.
Environment interpolation is allowed only for a field explicitly ending in `_env`; no secret value
may be written back to config, logs, SQLite, or exports.

Top-level fields:

```yaml
schema_version: 1
database_path: var/news-ingest.sqlite3
lock_path: var/news-ingest.lock
poll_interval_seconds: 300
homepage_poll_interval_seconds: 900
export_default_lookback_hours: 48
raw_payload_retention_days: null
max_response_bytes: 5242880
max_public_body_characters: 30000
failure_alert_threshold: 3
item_count_drop_warning_percent: 70
http:
  timeout_seconds: 15
  attempts: 3
  max_connections_per_host: 2
  user_agent: "VictorNewsCollector/1.0 (private personal use; contact configured locally)"
sources: {}
```

Each source has `enabled`, `identity`, optional `identity_pattern`, `language`,
`merge_across_feeds`, `fetch_article_pages`, `fetch_public_body`,
`capture_homepage_placement`, optional `homepage`, and `feeds`. Each feed has `id`, `name`, `url`,
`surface`, `order`, and `description_priority`. The optional `homepage` object has `id`, `url`, and
`surface: homepage`; it is present for Politiken but disabled by the source flag in release 1.

Populate the feed list exactly as follows:

- NYT: one feed, `nytimes.homepage`,
  `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`, surface `homepage_rss`.
- FT: `ft.homepage.international` using the direct `/rss/home/international` URL, followed by
  `ft.world`, `ft.global_economy`, `ft.companies`, `ft.markets`, `ft.technology`,
  `ft.climate_capital`, `ft.opinion`, `ft.work_careers`, and `ft.life_arts` using the verified
  `?format=rss` URLs listed in Section 2. Set the homepage feed to order 0 and the section feeds
  to deterministic orders 10 through 90. Use surface `homepage_rss` for the first and
  `section_rss` for the rest.
- Børsen: `borsen.homepage` (`https://borsen.dk/rss`) plus breaking, baeredygtig, ejendomme,
  finans, investor, executive, longread, markedsberetninger, opinion, pleasure, politik, tech,
  udland, virksomheder, and okonomi under `https://borsen.dk/rss/<name>`. The main feed is
  `homepage_rss`; all others are `section_rss`.
- Politiken: `politiken.latest`,
  `https://politiken.dk/rss/senestenyt.rss`, surface `latest_rss`.
- Berlingske: `berlingske.latest` at `https://www.berlingske.dk/content/rss`, followed by
  `berlingske.samfund`, `berlingske.business`, `berlingske.kultur`, and `berlingske.opinion` at
  `/content/3/rss`, `/content/66/rss`, `/content/69/rss`, and `/content/21/rss`. Use `latest_rss`
  for the all-news feed and `section_rss` for the category feeds.
- DR: `dr.latest`, then indland, udland, penge, politik, sporten, senestesport, viden, kultur,
  musik, vejret, regionale, regionale/kbh, regionale/bornholm, regionale/syd, regionale/fyn,
  regionale/vest, regionale/nord, regionale/trekanten, regionale/sjaelland, and
  regionale/oestjylland under `https://www.dr.dk/nyheder/service/feeds/`. Use `latest_rss` for
  `senestenyt`, and `section_rss` for the rest.

Set `description_priority=20` on DR section feeds and `10` on DR latest. Set it to `10` for every
other feed. This makes the DR richness rule configuration-driven: a nonempty section description
wins over a nonempty latest description. Within one priority tier the newest sighting from the same
feed wins, then the configured feed order breaks ties. Missing values never erase known ones.

Set all `fetch_article_pages` and `capture_homepage_placement` flags to false. Hard-code a config
validation error if NYT sets `fetch_article_pages=true`. FT page fetching is not hard-coded off, but
release 1 must leave it off and the optional implementation gate in Section 20 applies.

Configuration validation must reject:

- A schema version other than 1.
- Duplicate source IDs, feed IDs, feed URLs, or per-source feed order values.
- Non-HTTPS source URLs.
- Empty IDs/names, invalid identity values, or `url_regex` without a compilable pattern.
- Nonpositive intervals, timeouts, connection limits, attempts, or response sizes.
- A database or lock path that resolves outside the repository/runtime directory after explicit
  operator configuration.
- `fetch_public_body=true` when `fetch_article_pages=false`.
- Homepage capture for a source without a configured homepage surface.

`validate-config` prints the config hash, enabled sources, enabled feed IDs, and no secret values.

## 7. SQLite schema and transaction rules

Put the initial schema in `migrations/001_initial.sql`. `db.py` reads numbered migrations from the
filesystem, runs pending migrations in order under `BEGIN IMMEDIATE`, and records them in
`schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`.

Use TEXT for UTC timestamps, JSON, hashes, enums, and IDs. Add `CHECK(json_valid(...))` to JSON
columns when supported by the bundled SQLite. At connection startup execute:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
```

Create these tables and constraints:

### `fetch_runs`

- `run_id TEXT PRIMARY KEY` (UUID4 string)
- `started_at TEXT NOT NULL`, `ended_at TEXT`
- `status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed'))`
- `requested_source TEXT`
- `summary_json TEXT NOT NULL DEFAULT '{}'`
- `warnings_json TEXT NOT NULL DEFAULT '[]'`
- `error_json TEXT`

### `feed_polls`

- `poll_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `run_id TEXT NOT NULL REFERENCES fetch_runs(run_id)`
- `feed_id TEXT NOT NULL`, `source TEXT NOT NULL`
- `started_at TEXT NOT NULL`, `ended_at TEXT`
- `status TEXT NOT NULL` with values `running`, `not_modified`, `success`, `failed`
- `http_status INTEGER`, `attempt_count INTEGER NOT NULL DEFAULT 0`
- `sent_etag TEXT`, `sent_last_modified TEXT`, `received_etag TEXT`,
  `received_last_modified TEXT`
- `response_hash TEXT`, `response_bytes INTEGER`
- `raw_item_count INTEGER`, `parsed_item_count INTEGER`, `valid_item_count INTEGER`,
  `quarantined_item_count INTEGER`
- `feed_last_build_date TEXT`, `warning_json TEXT NOT NULL DEFAULT '[]'`, `error_json TEXT`

Index `(feed_id, poll_id DESC)` and `(run_id)`.

### `feed_state`

- `feed_id TEXT PRIMARY KEY`, `source TEXT NOT NULL`, `url TEXT NOT NULL`
- `etag TEXT`, `last_modified TEXT`, `last_response_hash TEXT`
- `last_checked_at TEXT`, `last_successful_poll_at TEXT`
- `last_item_count INTEGER`, `newest_published_at TEXT`
- `consecutive_failures INTEGER NOT NULL DEFAULT 0`
- `last_error_json TEXT`

Only a committed `304` or successfully parsed/committed `200` may advance validators and
`last_checked_at`. A failed HTTP request or unusable parse increments failure state in a separate
short transaction but never changes the last good validators.

### `raw_payloads`

- `content_hash TEXT PRIMARY KEY`
- `compression TEXT NOT NULL CHECK(compression='gzip')`
- `payload BLOB NOT NULL`
- `uncompressed_bytes INTEGER NOT NULL`
- `first_poll_id INTEGER NOT NULL REFERENCES feed_polls(poll_id)`
- `first_observed_at TEXT NOT NULL`

Store one gzipped copy of each distinct successful `200` body. `feed_polls.response_hash` points to
it. Do not store bodies for 304 responses. The retention command is a no-op when retention is null.

### `sightings`

- `sighting_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `poll_id INTEGER NOT NULL REFERENCES feed_polls(poll_id)`
- `feed_id TEXT NOT NULL`, `source TEXT NOT NULL`, `source_id TEXT NOT NULL`
- `item_position INTEGER NOT NULL CHECK(item_position > 0)`
- `publisher_order INTEGER`
- `observed_at TEXT NOT NULL`
- `normalized_json TEXT NOT NULL`
- `raw_metadata_json TEXT NOT NULL`
- `raw_item_json TEXT NOT NULL`
- `UNIQUE(feed_id, source_id, poll_id)`

`normalized_json` is the validated per-sighting candidate before cross-feed merging. Keep the raw
entry separately so parser and merge changes can be audited.

### `articles`

Create one row per `(source, source_id)` with columns matching every `ArticleSnapshot` field except
`schema_version`. Lists and raw metadata are canonical JSON strings. Add:

- `last_changed_at TEXT NOT NULL`
- `last_enrichment_status TEXT`
- `last_enrichment_success_at TEXT`
- `PRIMARY KEY(source, source_id)`

Index `published_at`, `last_changed_at`, `canonical_url`, and `(source, published_at)`.

### `article_versions`

- `version_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `source TEXT NOT NULL`, `source_id TEXT NOT NULL`
- `content_hash TEXT NOT NULL`, `observed_at TEXT NOT NULL`
- `snapshot_json TEXT NOT NULL` containing all hashed/versioned fields and explicit nulls
- foreign key `(source, source_id)` to `articles`

Do not add a uniqueness constraint on content hash. A → B → A creates three ordered versions.

### `appearances`

- `appearance_id INTEGER PRIMARY KEY AUTOINCREMENT`
- all `AppearanceRecord` fields except schema version
- `UNIQUE(poll_id, surface_id, position)`

Do not require an article foreign key: optional homepage placement can observe a stable publisher
ID before a matching feed item has been seen.

### `quarantine`

- `quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `poll_id INTEGER REFERENCES feed_polls(poll_id)`
- `feed_id TEXT NOT NULL`, `source TEXT NOT NULL`, `item_position INTEGER`
- `stage TEXT NOT NULL` (`http`, `feed`, `item`, `replay`, or `enrichment`)
- `error_code TEXT NOT NULL`, `error_json TEXT NOT NULL`
- `raw_item_json TEXT`, `created_at TEXT NOT NULL`, `resolved_at TEXT`

Never put an entire article body, authorization header, cookie, or secret in `error_json`.

### `enrichment_jobs`

Create the table now although release 1 does not enqueue work:

- `job_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `source`, `source_id`, `purpose`, `status`, `attempts`
- `last_attempt_at`, `last_success_at`, `next_retry_at`
- `etag`, `last_modified`, `parser_version`, `error_json`
- `UNIQUE(source, source_id, purpose)`

### Atomic per-feed transaction

For an HTTP 200, begin one transaction and perform all of these actions before commit:

1. Change the preallocated `feed_polls` row from `running` to its final success state inside the
   same transaction.
2. Insert the deduplicated raw payload.
3. Insert every valid sighting and every invalid item’s quarantine row.
4. Recompute every affected article from all committed plus current-transaction sightings.
5. Upsert article projections, including a new article before any version row that references it.
6. Append article versions only when hashed fields changed, then insert appearances.
7. Update the poll counts and success status.
8. Advance `feed_state` validators, last success, counts, and newest publication.
9. Commit.

On any database or structurally unusable feed error, roll back the transaction. Then write only a
failed poll/failure-state record in a new transaction. This preserves retryability.

## 8. Deterministic normalization rules

Implement pure helpers before orchestration. Every helper must have table-driven unit tests.

### Text

- Decode from raw response bytes through `feedparser`; never decode the XML to text first.
- Convert HTML entities, replace nonbreaking spaces with ordinary spaces, Unicode-normalize to
  NFC, collapse internal whitespace, and trim.
- Convert RSS descriptions to plain text with a conservative HTML fragment parser. Do not preserve
  scripts, styles, tracking pixels, or markup.
- Empty or whitespace-only optional text becomes `None`; required text raises a typed item
  validation error.

### Timestamp

`time.py` exposes `parse_feed_timestamp(original: str) -> datetime` and
`format_utc(datetime) -> str`.

- Require an explicit offset, `GMT`, or `UTC` for feed timestamps.
- Convert to UTC; never infer publication time from a URL or collection time.
- Preserve the original string.
- Unit tests cover `+0000`, `+0200`, `GMT`, CET/CEST boundaries, leap-day input, malformed values,
  and missing values.

### Identity

`identity.py` exposes `resolve_source_id(source_config, entry, raw_url) -> str`.

- NYT: nonempty RSS GUID.
- FT: nonempty RSS GUID UUID. Validate UUID syntax but keep its canonical lowercase text. Do not
  use `syn-*` URL parameters.
- Børsen: nonempty RSS GUID, canonical URL fallback only if GUID is missing.
- Politiken: the first `art([0-9]+)` match from raw URL; nonempty GUID fallback.
- Berlingske: complete nonempty `urn:bm:article:<uuid>` RSS GUID.
- DR: complete GUID string, including the `urn:dr:umbraco:<type>:` prefix. Never use canonical URL.

If a configured identity cannot be resolved, quarantine the item. Identity never crosses publisher
boundaries.

### URL handling

`urls.py` exposes `normalize_url(source, raw_url) -> canonical_url`.

- Require HTTP(S), lowercase scheme/host, remove default ports, normalize an empty path to `/`,
  remove a fragment from the canonical URL, and preserve the exact input in `raw_url`.
- Remove parameters whose names match `utm_*`, `b_source`, `b_medium`, or `b_campaign`.
- For FT also remove names matching `^syn-[A-Za-z0-9]+$`.
- For Berlingske remove `referrer=RSS` from canonical URLs while preserving it in raw URLs.
- Preserve all unrecognized parameters. Specifically preserve DR `focusId` with its original value
  and preserve the complete raw URL/fragment for live-blog entries.
- Do not sort or rewrite parameters in `raw_url`. Canonical query parameters may be sorted by key
  and value for deterministic comparison.
- Børsen `/nyhed/<numeric-id>` URLs encountered outside RSS require a real redirect/canonical
  resolution before deduplication; release 1 RSS processing must not perform this fetch.

### Generic feed mapping

`feed.py` exposes:

```python
parse_feed(payload: bytes, feed_config: FeedConfig, observed_at: datetime) -> ParsedFeed
normalize_entry(entry: Mapping[str, Any], context: EntryContext) -> SightingCandidate
json_safe_feedparser_value(value: Any) -> JSONValue
```

For every entry, map common `feedparser` fields rather than dispatching to a publisher module:

- `title`
- `link`
- `id`/`guid`
- `summary`/`description`
- `published` and parsed tuple only as a consistency check; the original string remains canonical
- `author`, `authors`, and `dc_creator`
- `tags[].term`
- `media_thumbnail`, `media_content`, and enclosures
- namespace fields such as NYT media credit/description and Politiken `pol:order`
- `links` entries, including NYT `rel=standout`

Serialize the complete entry recursively to JSON-safe primitives. Datetime structs become lists,
bytes become UTF-8 text with replacement plus a warning, and unknown objects become their safe
string representation plus a warning. Never drop the entire entry because one metadata field has
an unusual type.

Feed-level behavior:

- Count raw `<item` start tags from bytes for drift diagnostics.
- A `feedparser` bozo warning with usable entries is a warning, not automatic total failure.
- A response is structurally unusable when XML/RSS cannot be recognized, when raw item count is
  positive but parsed entry count is zero, or when feed identity contradicts configured
  expectations.
- Validate items independently. Missing title, URL/GUID identity, or timezone-aware `pubDate`
  quarantines only that item.
- Record one-based XML/parsed order as `item_position`.
- NYT and FT homepage position becomes `homepage_rss` appearance; Børsen main-feed position does
  the same. Berlingske's all-news feed remains `latest_rss` and must not be described as homepage
  placement.
- FT section position remains a weak `section_rss` signal. Do not present it as homepage rank.
- Politiken keeps both XML position and numeric `pol:order`.
- Every valid entry from every enabled feed is kept regardless of age.

## 9. Content merge, hashes, and versions

Implement `merge.py` as pure functions over a list of sightings sorted explicitly in SQL or Python.
Never depend on request completion order or default SQLite row order.

### Merge selection

For a `(source, source_id)`:

1. Group sightings by feed.
2. Within each feed, choose the newest nonempty value for each field. This allows a corrected shorter
   description to replace an older longer one from the same feed.
3. Across feeds, choose the nonempty value with the largest configured field priority; break ties by
   newest `observed_at`, then smallest configured feed order, then lexicographic feed ID.
4. For DR descriptions, section feeds win because their configured priority is 20 versus latest at
   10. HTML metadata, if optional enrichment is later enabled, has priority below RSS.
5. For FT, Børsen, and Berlingske duplicates across configured feeds, equal priority plus the
   explicit tie-breakers produces a stable result while every appearance remains available.
6. Union categories and keywords across current nonempty feed sightings, normalize, deduplicate, and
   sort. Deduplicate authors while preserving the chosen feed’s order.
7. Preserve the earliest `first_seen_at`, latest `last_seen_at`, and latest applicable
   `last_checked_at`.
8. A missing value never clears a known value in release 1. Publisher removals require a future
   explicit tombstone rule.

Select `raw_metadata` from the newest sighting contributing the chosen title, using the same
tie-breakers. Store description provenance as the winning stable feed ID, not merely `rss`.

### Canonical content hash

`hashing.py` builds a dict containing only the fields marked “Hashed” in Section 5, excluding the
`content_hash` field itself. Normalize set-like arrays, retain meaningful author order, serialize
with UTF-8, sorted keys, compact separators, and `ensure_ascii=False`, then calculate SHA-256.

- Observation timestamps, feed positions, raw payloads, raw metadata, HTTP state, and enrichment
  attempt state do not affect the hash.
- A new article inserts one version.
- A different hash appends a full version snapshot and changes `last_changed_at` to the commit time.
- The same hash changes only observation/provenance fields and creates no version.
- A → B → A appends three versions despite the repeated first hash.

`rebuild-articles` must call the same merge and hashing functions used by live collection.

## 10. HTTP client and polling behavior

Implement `http.py` around one shared `httpx.AsyncClient` per run. It returns a typed result rather
than writing to SQLite.

Required behavior:

- Send the configured descriptive user agent and `Accept` headers for RSS/XML.
- Apply connect/read/write/pool timeouts derived from the configured timeout.
- Limit response bodies before full allocation when possible; abort above
  `max_response_bytes` with a typed permanent error for that poll.
- Send `If-None-Match` and `If-Modified-Since` from last committed `feed_state`.
- Retry transport failures and HTTP 429, 500, 502, 503, and 504 up to `attempts` with bounded
  exponential backoff plus jitter.
- Honor both integer-seconds and HTTP-date `Retry-After`, capped at 60 seconds.
- Do not automatically retry ordinary 400, 401, 403, or 404.
- Classify a small HTML 403 challenge as `blocked`; record it without browser fallback.
- Return final URL, status, headers needed for provenance, raw bytes, attempt count, timings, and
  warnings. Redact cookies, authorization, API keys, and query secrets from all logs.

On 304, update check/health state and create no raw payload, sighting, version, or appearance. Also
advance `articles.last_checked_at`, without changing `last_seen_at`, for the source IDs present in
that feed's last successfully parsed representation. Resolve those IDs from the prior successful
poll's sightings; this records that the cached representation was checked without pretending it was
observed again. If no last response hash or prior successful sighting set exists in `feed_state`,
retry once without validators because a cached representation cannot be proven to have been
ingested.

Concurrency rules:

- Use a semaphore of two per host.
- Isolate feed failures with `asyncio.gather(..., return_exceptions=True)` or equivalent handling.
- Database writes may be serialized even when HTTP requests overlap.
- The process lock covers all commands that mutate the database. A second process exits with a
  machine-readable `lock_busy` error; it does not wait indefinitely.

## 11. Collection orchestration

`collect.py` coordinates one run:

1. Validate config, acquire the process lock, migrate/open the database, and create a running
   `fetch_runs` row.
2. Resolve the enabled sources/feeds, respecting `--source` without changing the configured set in
   the manifest.
3. Load committed feed validators and preallocate one `feed_polls(status='running')` row per planned
   request in a short transaction. A process crash can therefore be reported as an abandoned poll.
4. Fetch feeds concurrently within per-host limits using those poll IDs for logs only.
5. Handle each completed response through the exact transaction in Section 7. On failure, roll back
   ingestion and mark the preallocated poll failed in a separate transaction.
6. Continue after any individual feed failure.
7. Compute source status after all feeds finish. If every enabled feed for a source failed, add an
   immediate source outage warning.
8. Mark the run `success` when all selected feeds succeeded or were valid 304s, `partial` when some
   failed, and `failed` only when none succeeded or a run-level invariant failed.
9. Emit a run result containing request/304/retry/failure counts; parsed, new, updated, unchanged,
   and quarantined counts; merge-description provenance counts; per-source newest publication and
   ingestion lag; and all warnings.
10. Release the lock in `finally`.

`collect --once` runs once. `collect` without `--once` loops using
`poll_interval_seconds`, handles SIGINT/SIGTERM between polls, and reuses no HTTP client across
runs. Production scheduling should call `collect --once`; the loop exists for local observation.

## 12. CLI contract

Implement argparse in `cli.py`, with `__main__.py` delegating to `main()` and this console entry:

```toml
[project.scripts]
news-ingest = "news_ingest.cli:main"
```

Commands:

```text
news-ingest validate-config [--config PATH]
news-ingest collect [--config PATH] [--source SOURCE] [--once]
news-ingest export --since ISO --until ISO --format jsonl --output PATH
news-ingest export --changed-since ISO --format jsonl --output PATH
news-ingest health [--config PATH]
news-ingest rebuild-articles [--source SOURCE]
news-ingest replay-payloads --since ISO [--source SOURCE]
news-ingest backup --output PATH
news-ingest restore-check --backup PATH
news-ingest live-contracts [--source SOURCE]
news-ingest enrich [--source SOURCE] [--missing-description] [--limit N]
news-ingest snapshot-homepages [--source SOURCE]
```

The last two commands must exist in release 1 but return a successful, explicit `disabled` result
when no corresponding source flag is enabled. They must not fetch pages silently.

Every stdout response is one JSON object:

```json
{"ok": true, "action": "collect", "result": {}, "warnings": [], "schema_version": 1}
```

or:

```json
{"ok": false, "action": "collect", "error": {"type": "...", "message": "...", "details": {}}, "schema_version": 1}
```

Use exit code 0 for success, including a collection with explicit partial source failures. Use exit
code 1 for total failure or invalid arguments/config. Never print argparse usage to stdout.

## 13. Export implementation

`export.py` supports two mutually exclusive selection modes:

- Publication window: `since <= published_at < until`.
- Changed since: `last_changed_at >= changed_since` regardless of publication time.

Reject a mixed mode, a non-UTC/naive boundary, `since >= until`, an unsupported format, or an
already existing output directory.

### Consistent snapshot and boundary

1. Open a read-only SQLite connection and `BEGIN` a read transaction.
2. Establish the snapshot with the first database read.
3. Capture `generated_at` in UTC.
4. Select articles and appearances from that same transaction.
5. For changed-since export, include rows below `generated_at`; the next consumer request uses this
   manifest `generated_at` with an inclusive lower bound. Boundary duplicates are acceptable and
   prevent misses.
6. Sort articles by `published_at`, `source`, `source_id`. Sort appearances by `observed_at`,
   `source`, `source_id`, `surface_id`, `position`.

Publication-window exports include appearances for selected articles through `generated_at`, with
their actual observation times. Changed-since exports do the same for changed articles. Do not
pretend missing placement is rank zero; represent missing/stale placement through manifest coverage
gaps.

### Atomic bundle publication

The `--output` target is an immutable directory. Create a uniquely named temporary sibling on the
same filesystem, then:

1. Stream Pydantic-validated records to `articles.jsonl` with explicit nulls.
2. Write `appearances.jsonl` when at least one appearance exists.
3. Hash and count the final bytes of each data file.
4. Build and validate `manifest.json`, including operational feed/quarantine coverage.
5. Flush and `fsync` each file, then the staging directory.
6. Rename the staging directory to the requested output path atomically.
7. On failure, leave no published target; clean only the unique staging directory created by this
   process.

Do not overwrite an existing bundle. A repeated query may produce a different later bundle because
the database may have learned about late articles or corrections.

Add JSON Schema snapshots only if a downstream consumer asks for them. In release 1, Pydantic model
validation plus fixture/golden JSONL tests define the contract.

## 14. Rebuild, replay, backup, and health

### Rebuild

`rebuild-articles [--source]` computes a complete replacement projection from sightings into
temporary database tables, compares counts/hashes, and swaps inside one transaction. Preserve
historical `article_versions`; do not append versions during a rebuild. Fail and leave the existing
projection untouched if any sighting cannot be parsed or any rebuilt article fails validation.

Provide `--dry-run` even though it was not in the original CLI sketch. It returns rows added,
removed, and changed by source without mutation. Tests must prove a clean rebuild reports zero
semantic differences.

### Replay

`replay-payloads --since` decompresses retained payloads in poll order, parses them with current
code, and writes to isolated temporary replay tables. It must not rewrite original sightings by
default. Compare replayed sightings/projections with live data and emit differences. Add
`--apply` only in a later change with a separately reviewed migration plan; release 1 is diagnostic.

### Backup and restore check

Use `sqlite3.Connection.backup()` under a read transaction to create a new backup file. Refuse to
overwrite. `restore-check` copies the supplied backup into a unique temporary file, runs
`PRAGMA integrity_check`, migrations in check-only mode, projection counts, and a small export; it
never changes the active database.

Document how to copy immutable export bundles and SQLite backups, and that copying the live main
database file without the WAL files is unsupported.

### Health

`health.py` reports:

- Database/migration/integrity status.
- Lock availability without stealing the lock.
- Per-feed last check, last success, consecutive failures, last item count, newest publication, and
  ingestion lag.
- Warning after three consecutive failures (configurable).
- Immediate warning when all feeds for a publisher failed in the latest run.
- Warning when a successful 200 yields zero items or item count drops by more than the configured
  percentage from the prior successful nonzero count.
- Source-specific no-new-item staleness. Start with configurable defaults
  (NYT/FT/Politiken/Berlingske/DR 6 hours, Børsen 4 hours), label them heuristics, and suppress the warning until two successful
  polls exist.
- Unresolved quarantine counts and oldest age.
- Last export/backup status if known.
- A top-level status of `healthy`, `degraded`, or `failed` with explicit reasons.

## 15. Fixture and test policy

All normal tests are network-free. Save dated raw response fixtures before depending on a parser.
`tools/capture_fixture.py` is the only fixture-capture helper and must:

- Accept a configured feed ID and destination fixture name.
- Use the shared HTTP policy with no authentication.
- Write raw response bytes plus a JSON sidecar containing URL, final URL, capture time, safe
  response headers, SHA-256, status, parser expectations, raw item count, and content encoding.
- Refuse to overwrite.
- Remove cookies and security headers that could carry identifiers.

At minimum capture:

- NYT homepage.
- FT international homepage and one section feed with an article duplicated between feeds when
  available.
- Børsen main and one category feed, plus a fixture containing a short `/nyhed/<id>` alias if it can
  be obtained without page automation.
- Politiken latest in its declared ISO-8859-1 form and entries with `pol:order`/entities.
- Berlingske all-news plus one category feed sharing a full article GUID.
- DR latest plus a section feed sharing a GUID where only the section has a description, and a live
  blog URL with `focusId` when available.
- Malformed/truncated synthetic variants derived from the structural shape, not copied full
  articles.

Do not place full subscriber article bodies in fixtures.

### Unit and integration test inventory

Implement these named behaviors; combine cases only when failure output remains clear:

- `test_config.py`: valid full config; every rejection in Section 6; stable secret-free config hash.
- `test_time.py`: all timestamp cases in Section 8.
- `test_urls.py`: tracking removal; FT dynamic `syn-*`; Berlingske `referrer=RSS`; DR `focusId`;
  fragments/raw URL; Børsen canonical fallback.
- `test_identity.py`: all six source policies; Politiken fallback; FT UUID; Berlingske and DR live
  GUIDs.
- `test_feed.py`: one fixture per source/feed shape; declared Politiken encoding; entities/NBSP;
  NYT namespaces/standout; FT homepage order and thumbnail; Børsen author/image; Politiken
  `pol:order`; Berlingske author/image enclosure; DR missing description; bozo warning; per-item
  quarantine; raw/parsed count mismatch.
- `test_http.py` with `respx`: redirects; ETag/Last-Modified; 304; 304 without cached payload;
  retryable statuses; both Retry-After forms; timeout; oversized body; non-retried 403/404; secret
  redaction.
- `test_merge.py`: DR priority; FT duplicate across home/section; corrected shorter description;
  missing value retention; completion-order independence; array normalization; raw metadata choice.
- `test_db.py`: migration idempotence; pragmas; constraints; transaction rollback; validators do not
  advance on parse/commit failure; A → B → A versions; observation-only no-version update.
- `test_collect.py`: unchanged repeated 200; 304; one-feed failure; all-source-feed failure; partial
  run; per-host concurrency cap; process lock.
- `test_replay.py`: raw payload dedup/gzip; replay comparison; rebuild exactness; failed rebuild
  leaves projection unchanged.
- `test_export.py`: explicit nulls; deterministic ordering/bytes; both modes; late discovery;
  correction to old article; consistent snapshot; manifest coverage; atomic publish; refuse
  overwrite; cleanup after injected failure.
- `test_health.py`: every threshold and top-level state.
- `test_enrichment.py` and `test_homepage.py`: release 1 flags yield explicit disabled results and
  make zero HTTP calls.

Use temporary directories/databases in every test. Freeze/inject the clock and jitter source rather
than sleeping. Do not assert against log wording when a structured code is available.

### Live contract tests

Mark all tests in `tests/live/` with `@pytest.mark.live` and exclude them from the default suite.
The `live-contracts` command fetches one representative feed for each selected source and checks:

- HTTP 200/304 behavior and XML parseability.
- At least one item on a fresh 200.
- Parsed entry count equals raw `<item` count.
- Required title, identity, URL, and timezone-bearing publication timestamp coverage.
- Missing-description percentage has not moved catastrophically from the saved baseline.
- FT homepage feed has a plausible 5–30 items, UUID GUIDs, GMT/offset timestamps, and a valid
  ordered item list; a count outside the band is a contract warning, not a parser rewrite.
- The configured feed self-description/host still agrees with the selected publisher.

Run this command separately once per day. A live failure raises an operational warning; it does not
make the offline unit suite flaky.

## 16. Work packages and completion gates

### Work Package 1 — package scaffold

Files: `.gitignore`, `pyproject.toml`, `uv.lock`, `README.md`, `src/news_ingest/__init__.py`,
`src/news_ingest/__main__.py`, `tests/conftest.py`.

Steps:

1. Initialize the Python 3.12 package and exact dependencies.
2. Configure pytest and the `live` marker.
3. Ignore `var/`, `.env`, temporary export directories, coverage/caches, and fixture capture scratch
   files. Do not ignore committed fixtures or migrations.
4. Add a placeholder CLI that returns the version in the JSON envelope.
5. Document scope and non-goals in README.

Complete when `uv run news-ingest --version`, `uv run pytest`, and a fresh `uv sync --locked`
succeed.

### Work Package 2 — configuration

Files: `config/sources.yaml`, `src/news_ingest/config.py`, `tests/test_config.py`.

Implement Section 6 exactly. Complete when invalid configuration cannot start any mutating or
network command and `validate-config` prints all six enabled sources and no credentials.

### Work Package 3 — models and pure normalization

Files: `models.py`, `time.py`, `urls.py`, `identity.py`, `hashing.py` and their tests.

Implement Sections 5, 8, and 9 without database or network calls. Complete when the models emit
explicit nulls, hashes are byte-for-byte stable across dictionary/list input order where semantics
are set-like, and all identity/URL/time cases pass.

### Work Package 4 — initial migration and database API

Files: `migrations/001_initial.sql`, `db.py`, `tests/test_db.py`.

Expose narrow repository methods; do not scatter SQL across commands:

- migration/connect helpers
- start/finish run and poll
- get/update feed state
- insert payload/sighting/quarantine/appearance
- load sightings for article keys
- upsert projection/append version
- read snapshot queries for export/health

Complete when migration and rollback tests pass and a failed transaction demonstrably leaves old
validators intact.

### Work Package 5 — saved fixtures

Files: `tools/capture_fixture.py`, `tests/fixtures/**`, `docs/source-contracts.md`.

Capture the minimum fixture set in Section 15, record observations rather than promises, and add a
manifest. The FT source contract must record the international homepage scope, ten-item observation,
15-minute feed TTL, ETag, UUID GUID, `syn-*` tracking parameter, and section-feed observations.

Complete when every fixture hash matches the manifest and no fixture contains credentials, cookies,
or full subscriber text.

### Work Package 6 — generic feed parser

Files: `feed.py`, `tests/test_feed.py`.

Implement mapping/validation from Section 8. Complete when all six publishers parse through the
same entry path, the parser retains complete JSON-safe metadata, and invalid siblings quarantine
without discarding valid entries.

### Work Package 7 — HTTP client

Files: `http.py`, `tests/test_http.py`.

Implement Section 10 entirely against `respx`. Complete when retry/304/size/redaction behavior is
deterministic under an injected clock and random source.

### Work Package 8 — merge and persistence pipeline

Files: `merge.py`, extensions to `db.py`, `tests/test_merge.py`, `tests/test_db.py`.

Implement the per-feed transaction and version rules. Complete when DR and FT cross-feed duplicates
merge deterministically, appearances from every feed remain, repeat polls are idempotent, and crash
injection at every transaction stage either fully commits or fully rolls back.

### Work Package 9 — collector and CLI

Files: `collect.py`, `cli.py`, `tests/test_collect.py`.

Implement run orchestration, process locking, partial failures, stdout/stderr discipline, and both
one-shot/loop behavior. Complete when one simulated publisher outage still commits and reports all
other sources and when overlapping writers are rejected.

### Work Package 10 — exports

Files: `export.py`, `tests/test_export.py`.

Implement Section 13. Complete when golden JSONL bytes are deterministic, manifests verify every
file, injected failure never exposes a partial target, and both late discoveries and old-article
corrections appear in changed-since output.

### Work Package 11 — recovery and health

Files: `replay.py`, `health.py`, CLI wiring, `tests/test_replay.py`, `tests/test_health.py`.

Implement rebuild dry-run/apply, diagnostic replay, backup/restore check, and health rules. Complete
when a restored fixture database passes integrity/export and a rebuild reproduces article hashes and
counts exactly.

### Work Package 12 — operations documentation and scheduling

Files: `docs/operations.md`, `docs/scheduling.md`, README updates.

Document:

- Initial `uv sync --locked`, config validation, first collect, health, and export commands.
- A five-minute external schedule for `collect --once`; show both a macOS launchd example and a
  portable cron/systemd-timer equivalent without installing either automatically.
- A separate daily live-contract check.
- Log rotation, disk monitoring for raw payloads, feed alerts, immutable export cleanup policy, and
  how to inspect quarantine without exposing article text in alerts.
- Backup and restore-check commands.
- Upgrade order: stop scheduler, back up, migrate/test, restart, check health.
- Completeness language: only items observed in configured feeds are covered.

Complete when a new operator can follow the documentation against a clean temp directory without
reading source code.

### Work Package 13 — first-release validation and 48-hour soak

Before starting, run:

```text
uv sync --locked
uv run pytest -m "not live"
uv run news-ingest validate-config
uv run news-ingest live-contracts
uv run news-ingest backup --output <new backup path>
uv run news-ingest restore-check --backup <backup path>
```

Run collection every five minutes for 48 hours. Restart the process at least once during the soak.
At the midpoint and end:

1. Run health and save its JSON.
2. Account for every parsed item as a committed sighting or quarantine row.
3. Confirm no unchanged poll created duplicate sightings/articles/versions.
4. Compare raw item counts with parsed + quarantined counts per successful feed poll.
5. Run `rebuild-articles --dry-run`; require zero unexplained differences.
6. Run replay over the soak interval; require the same identities and derived hashes.
7. Create a publication-window export and validate all file hashes/counts.
8. Create a changed-since export, ingest a fixture representing a late article and a correction,
   then confirm both arrive in the next changed-since bundle.
9. Confirm each feed outage and 304 is represented accurately.
10. Report per-source description coverage. This report decides whether enrichment has any value.

First release is complete only when all acceptance criteria in Section 19 pass. A soak cannot prove
that no item disappeared between polls; the report must retain that limitation.

## 17. Structured logging and metrics

Use the standard `logging` module with one JSON object per stderr line. Every event has `timestamp`,
`level`, `event`, `run_id`, and applicable `feed_id`/`poll_id`; avoid custom prose-only messages.

The final run summary contains:

- HTTP request, 304, retry, byte, and failure counts.
- Parsed, valid, quarantined, new, updated, and unchanged item counts.
- Duplicate merges and winning description feed IDs.
- Per-source newest publication time and ingestion lag.
- Access-status counts.
- Export record counts and validation failures when applicable.

Never log raw payloads, full descriptions/bodies, cookies, authorization headers, API keys, or
subscription credentials. URL logging must redact configured secret query parameters.

## 18. CI/check sequence

Configure a single offline default check, even if no hosted CI is installed yet:

```text
uv sync --locked
uv run python -m compileall -q src tests
uv run pytest -m "not live" -q
uv run news-ingest validate-config
```

If a formatter/linter is added, use Ruff as one pinned development dependency and insert
`uv run ruff check .` plus `uv run ruff format --check .` before pytest. Do not introduce mypy or a
second style tool unless a concrete defect justifies it.

Live tests are a separate scheduled command and must never gate an offline pull request merely
because a publisher is unavailable.

## 19. First-release acceptance criteria

All items below are mandatory:

- One command polls every configured feed from all six sources with no LLM or browser.
- Repeating an unchanged 200 or processing a 304 creates no duplicate article or version.
- Every valid export has stable identity, title, raw URL, timezone-normalized publication time,
  first-seen time, and content hash, with nullable fields explicitly emitted.
- FT GUID UUIDs merge homepage/section duplicates while every feed appearance remains. FT homepage
  order is available as the source’s primary prominence signal; section order is labeled weak.
- FT subscription credentials/cookies are absent from config, storage, logs, fixtures, and runtime.
- DR same-GUID records merge, section descriptions win deterministically, and every feed appearance
  remains.
- Politiken `pol:order`, XML feed position, and future homepage position remain distinct.
- Berlingske full GUIDs merge all-news/section duplicates while every feed appearance remains.
- NYT, FT, and Børsen homepage-feed positions are preserved.
- No cross-publisher deduplication occurs.
- Any UTC publication window exports a schema-valid deterministic bundle.
- A late article and a correction to an older article both arrive through changed-since export.
- Failure of one publisher still commits the others and produces a visible partial warning.
- All ordinary tests run without network access.
- Validators never advance past rolled-back or unparsed data.
- A → B → A creates three versions; observation-only time/position changes create none.
- Conflicting feed descriptions resolve identically regardless of HTTP completion order.
- Rebuild reproduces the current projection exactly; replay reproduces identities/sightings from raw
  payloads.
- Backup restoration, quarantine handling, and atomic export failure tests pass.
- The 48-hour soak accounts for every parsed item as persisted or quarantined, survives a restart,
  and records outages explicitly.

## 20. Optional Work Package 14 — article enrichment

Do not begin until the 48-hour description-coverage report exists and a downstream need is written
down. Enrichment remains separate from collection through `enrichment_jobs`; it never delays or
rolls back RSS ingestion.

Source gates:

- NYT: never fetch article pages. Keep `metadata_only`.
- FT: keep RSS-only by default even though the operator has a subscription. Subscription login does
  not make cookie automation portable or stable. Do not store/reuse browser cookies or automate
  login. Only implement FT full-text access if FT provides a documented mechanism permitted for the
  account, the user explicitly selects it after reviewing that mechanism, and credentials remain in
  an external secret store. Otherwise use RSS descriptions and keep `metadata_only`.
- Børsen: enable only if RSS descriptions have a measured gap. Parse every JSON-LD block and select
  the `NewsArticle` whose URL matches canonical. Interpret both boolean false and string `"False"`
  paywall flags. Prefer RSS `pubDate`; use page `dateModified` only for `modified_at`. At most three
  publicly visible paragraphs may be stored.
- Politiken: leave disabled unless a measured gap appears. Pages add little beyond canonical URL and
  a published `<time>`.
- Berlingske: keep RSS-only unless a measured description-coverage gap and downstream requirement
  pass this package's gate. Do not add login or subscriber-cookie handling.
- DR: if bodies are required, parse `script#__NEXT_DATA__`, choose the publication whose URL matches
  canonical, traverse `props.pageProps.viewProps.site.publications[].content`, and extract structured
  body paragraphs. Never use hashed CSS classes. Cap at 30,000 characters and set the truncation
  flag. Extraction failure yields null and retains prior data.

Common metadata order is JSON-LD matching canonical URL, canonical link, OpenGraph title, `<h1>`,
RSS description, JSON-LD description, meta description, OpenGraph description, then modified time.
Public body is attempted only when explicitly enabled. A small HTML 403 challenge is `blocked` with
no retry/browser fallback.

Tests remain fixture-based and include multiple JSON-LD article blocks, string paywall booleans,
blocked challenges, cached unchanged pages, durable retry scheduling, and retention of previous text
after a failed refresh.

## 21. Optional Work Package 15 — homepage placement

Do not build HTML placement for FT. The ordered international homepage RSS feed is the portable,
layout-independent FT prominence source. Do not build NYT homepage HTML either. Use Børsen main-feed
order and periodically compare it with the visible homepage only as an opt-in live contract check.

The only planned HTML placement adapter is Politiken:

1. Conditional GET `https://politiken.dk/` with the shared plain HTTP client.
2. Select elements carrying `data-article-id` and `data-element-type="article"`.
3. Record article ID, first one-based document order, `data-page-section`, and
   `data-is-super-article`.
4. Exclude `data-page-section="navigation"` and keep only the first occurrence of each article ID.
5. Store appearances with `surface=homepage`; never scrape headline/card geometry or use a browser.
6. Treat fewer than a plausible configured number of IDs or absence of `tophat`/`topgrid` as a
   missing placement snapshot plus warning, not a collection failure.

Keep DR homepage capture disabled until the downstream consumer demonstrates a need. Its frontend
differs from article pages and is the least stable surface.

## 22. Explicit deferrals

These are outside this implementation unless a new plan is approved:

- NYT Article Search and Top Stories APIs.
- FT authenticated article extraction, browser-cookie import, or full-text archive.
- Any browser/Playwright dependency.
- Cross-publisher story clustering, ranking, or summaries.
- Historical crawling before the collector’s first observation.
- Web UI, REST service, message queue, distributed workers, or multi-host database.
- Automatic mutation of existing exports or original sightings.
- Commercial redistribution or republication.

The handoff is successful when the receiving agent can implement each work package without choosing
a new architecture, and every choice that could expand access or fragility is held behind an explicit
gate.
