# AGENTS.md

## Project overview

`ingest/` contains the `news-ingest` Python 3.12 service and CLI, block 1 of the `copenhagen-daily` repository. It polls
configured first-party RSS feeds from NYT, FT, Børsen, Politiken, Berlingske, DR,
TV 2, Jyllands-Posten, Information, Altinget, Kristeligt Dagblad, BBC News, The
Economist, The Guardian, The Washington Post, and The Wall Street Journal,
persists raw payloads and every valid sighting in SQLite, builds a deterministic
article projection, and publishes immutable JSONL export bundles.

The detailed product and implementation contract is
`../plans/news-ingestion-implementation-plan.md`. Treat it as authoritative when a
requirement is not summarized here.

## Non-negotiable boundaries

- Ingestion must be deterministic and must never call an LLM.
- First-party RSS is the release-1 source of truth.
- Persist every valid observed feed item, including old items and duplicates
  across feeds.
- Raw payloads and sightings are facts. The `articles` table is a rebuildable
  projection.
- Advance HTTP validators only in the same transaction as successfully parsed
  and committed data. A valid `304` is the only exception.
- Isolate publisher/feed failures and make them visible in structured output.
- Exports must be schema-validated, deterministic, immutable, and atomically
  published.
- Do not add browser automation, login automation, subscriber-cookie handling,
  paywall bypasses, archive crawling, ranking, summarization, rewriting, or
  cross-publisher story clustering.
- Do not fetch NYT article pages. Article enrichment and HTML homepage capture
  remain disabled until their gates in the plan are explicitly met.
- Coverage means items observed in configured feeds while the collector runs;
  never claim complete publisher or historical coverage.

## Repository conventions

- Use Python 3.12+, a `src/` layout, and the `news_ingest` import package.
- Manage dependencies with `uv`. Keep every direct dependency exactly pinned in
  `pyproject.toml` and commit the regenerated `uv.lock`.
- Keep publisher feed behavior in `config/sources.yaml`. Do not introduce a
  publisher-adapter hierarchy or a module per publisher.
- Keep boundary models in `src/news_ingest/models.py` and reject unknown fields.
- Keep normalization, identity, URL, timestamp, merge, and hashing logic pure
  where possible.
- Keep SQL behind the narrow database API in `src/news_ingest/db.py`; commands
  should not scatter SQL across the package.
- Store UTC timestamps as RFC 3339 text with six fractional digits and a `Z`.
- Preserve exact publisher URLs in `raw_url`; apply tracking cleanup only to
  `canonical_url`.
- JSON written to stdout is the CLI contract. Diagnostics and one-object-per-line
  structured logs belong on stderr. Never log raw payloads, full descriptions,
  bodies, cookies, authorization headers, API keys, or credentials.
- Use the process lock for every database-mutating command. A second writer must
  return a machine-readable `lock_busy` error rather than wait indefinitely.
- Use explicit ordering in SQL or Python whenever output or merging must be
  deterministic. Never rely on SQLite's default row order or HTTP completion
  order.

## Data and transaction rules

- Use one transaction per successful HTTP `200` feed response.
- Within that transaction, store the compressed raw payload, sightings,
  quarantines, article projections and versions, appearances, final poll state,
  and updated feed validators.
- Roll the entire ingestion transaction back on an unusable feed or database
  error, then record only the failed poll and failure state in a short separate
  transaction.
- A `304` creates no payload, sighting, version, or appearance.
- Repeated unchanged content must not create an article version.
- Content transitions `A -> B -> A` must create three ordered versions.
- Never delete or rewrite original sightings during replay or rebuild.
- Do not overwrite an existing export directory or backup file.
- Do not copy a live SQLite main file without its WAL files; use the backup
  command instead.

## Source-specific invariants

- NYT identity is its nonempty RSS GUID. Feed placement is one-based order and
  may preserve `rel="standout"` metadata.
- FT identity is its canonical lowercase UUID GUID. Remove dynamic `syn-*`
  parameters from canonical URLs, retain them in raw URLs, and treat section
  order as a weak section signal rather than homepage rank.
- Børsen uses its nonempty GUID, with canonical URL fallback only when the GUID
  is absent.
- Politiken uses the first `art([0-9]+)` URL match, with GUID fallback. Keep
  `pol:order` distinct from XML position.
- Berlingske keeps the complete `urn:bm:article:<uuid>` RSS GUID. Remove only
  `referrer=RSS` from canonical URLs and retain it in raw URLs. Treat the all-news
  feed as latest-news evidence and category feeds as weaker section evidence.
- DR keeps the complete GUID URN. Section-feed descriptions outrank latest-feed
  descriptions through configured priorities. Preserve `focusId` URL values.
- TV 2 uses its permalink GUID from the single first-party news feed at
  `feeds.services.tv2.dk`. The feed ignores query parameters, so there are no
  section feeds; treat it as latest-news evidence only.
- Jyllands-Posten uses the first `ECE([0-9]+)` URL match, with GUID fallback.
  `topnyheder` is an editorially ordered top-stories surface; `seneste` is
  latest-news evidence. Both public `feeds.jp.dk` aliases redirect to a
  publisher-owned newsletter proxy and are capped at ten items.
- Information uses its Drupal GUID (`<node id> at https://www.information.dk`)
  from its single site-wide feed.
- Altinget uses its URL GUID. The front feed is latest-news evidence; the
  `/<section>/rss` feeds are weaker section evidence.
- Kristeligt Dagblad uses its UUID GUID. Its `pubDate` values are ISO 8601, so
  timestamp parsing accepts ISO 8601 after RFC 2822.
- Weekendavisen and Zetland publish no first-party RSS feed and are therefore
  not monitored. Weekendavisen exposes a Google News sitemap instead.
- BBC uses the article id from the URL path (`/articles/<id>`, `/videos/<id>`,
  `/live/<id>`), with GUID fallback, because BBC GUIDs carry a per-feed `#N`
  fragment that would split one article into several identities. The top-stories
  feed is a ranked homepage surface.
- The Economist uses its UUID GUID; every feed carries 300 items. The Guardian,
  The Washington Post, and The Wall Street Journal use their GUIDs. The Guardian
  international feed is a ranked homepage surface. WSJ feeds live at
  `feeds.content.dowjones.io`; the old `feeds.a.dj.com` aliases are stale.
- Reuters and the Associated Press publish no first-party RSS feed (Reuters
  returns 401, AP 403 to every client) and are therefore not monitored.
- A publisher may list the same article twice in one feed snapshot (BBC and WSJ
  do). The first placement is the sighting; later repeats are quarantined with
  `duplicate_in_snapshot` so the poll still succeeds.
- Never deduplicate identities across publishers.

## Publisher-prominence contract

- Prominence is observation metadata, not article content. It must not affect
  `content_hash` or article version creation.
- Derive scores in `src/news_ingest/prominence.py` on a source-local 0–1 scale.
  Normalize rank by the number of items in that observed snapshot.
- `homepage` and `homepage_rss` evidence has a 1.0 ceiling,
  `latest_rss` has a 0.65 ceiling, and `section_rss` has a 0.50 ceiling.
- Scores of at least 0.75 are `high`, at least 0.40 are `medium`, and lower
  scores are `low`.
- Prefer Politiken's explicit `publisher_order` to XML position when present;
  retain both underlying values.
- Every appearance export must include `snapshot_item_count`,
  `prominence_score`, `prominence_tier`, and `prominence_evidence` so downstream
  consumers can audit the score.
- Every article export may summarize its strongest observed placement in the
  nullable `publisher_prominence` object. Keep all observations in
  `appearances.jsonl` as the evidence trail.
- Describe evidence precisely. For example, "ranked first in the FT
  International Homepage RSS snapshot" is valid; "main visual article on
  ft.com" is not established by RSS alone.

## Working with configuration

- Load YAML with `yaml.safe_load` and validate it before any mutation or network
  request.
- Require HTTPS publisher URLs and unique feed IDs, URLs, and per-source orders.
- Reject runtime database and lock paths that resolve outside the configured
  repository/runtime directory.
- Environment interpolation is allowed only for fields ending in `_env`; never
  serialize resolved secrets to config, SQLite, logs, or exports.
- Preserve the full configured feed set in export metadata even when collection
  is filtered with `--source`.

## Tests and fixtures

- All default tests must be network-free and use temporary databases/directories.
- Put network-backed checks under `tests/live/`, mark them `live`, and exclude
  them from the ordinary test suite.
- Use `gather_news.sh capture-fixture` as the only normal fixture-capture path;
  `tools/capture_fixture.py` is a compatibility shim. Raw
  fixtures need safe metadata sidecars and hashes, and must never contain
  credentials, cookies, or subscriber article bodies.
- Add table-driven tests for normalization rules and regression tests for every
  fixed defect.
- Freeze or inject clocks, retry sleeps, and jitter sources; do not make tests
  sleep.
- Assert structured error codes or fields instead of human log wording.

## Required verification

Run the offline check before handing off code changes. All verification is
routed through the allowlist-friendly repository entrypoint; do not invoke
`uv`, Python, Ruff, or pytest directly:

```sh
./gather_news.sh check
```

This assumes the operator has already provisioned `.venv` from the committed
`uv.lock`; the wrapper deliberately cannot install or update dependencies.

For changes affecting persistence, collection, recovery, or exports, also run
the smallest relevant CLI smoke test against a temporary database. Do not use or
overwrite `var/news-ingest.sqlite3` in tests.

Live publisher checks are separate and must be explicitly requested or clearly
required by the task:

```sh
./gather_news.sh live-contracts
```

Do not treat a publisher outage as an offline-test failure.

## Change discipline

- Prefer focused changes that preserve the architecture in the plan. Do not add
  a web framework, ORM, queue, web UI, distributed workers, or multi-host
  database without a newly approved plan.
- Preserve existing user data and unrelated worktree changes.
- Add migrations for schema changes; never edit a deployed database by hand.
- Keep migrations forward-only, numbered, explicit, and idempotently applied.
- Update README/operations/source-contract documentation when behavior or
  operator expectations change.
- Optional work packages 14 and 15 must not begin until their documented gates
  are satisfied and the user explicitly approves the expanded scope.
