---
name: news-ingest
description: Operate and maintain the ingest/ RSS ingestion block of the copenhagen-daily repository through its whitelisted JSON CLI. Use for collecting feeds, checking health, exporting or backing up data, capturing fixtures, validating changes, or modifying the news_ingest codebase. Do not use for downstream LLM selection, summarization, or newspaper rendering.
---

# News Ingest

`ingest/` (the `news-ingest` package, block 1 of the `copenhagen-daily` repository) is the deterministic acquisition block for a personal newspaper. It polls configured first-party RSS feeds, preserves every valid sighting and raw response, rebuilds an article projection, records publisher placement, and emits immutable JSONL bundles. It never calls an LLM or deduplicates across publishers.

## One executable

Run every application, fixture, and verification workflow through:

```sh
<repo>/ingest/gather_news.sh <action> [options]
```

Call the executable directly. Do not prefix it with `uv run`, `python`, or another environment launcher. It resolves the repository and `.venv` itself, so the absolute path can be allowlisted and invoked from any working directory.

Every non-help call emits exactly one JSON object on stdout and nothing else; there is no stderr log. Parse `ok`, then `result` or `error.type`. Feed errors are stored in the database and surfaced by `health`. Exit `0` means success, `2` means malformed arguments, and `1` means a well-formed action failed. `meta.schema_version` identifies the output contract. Run `list-actions` instead of guessing flags.

## Common workflow

```sh
./gather_news.sh list-actions
./gather_news.sh validate-config
./gather_news.sh collect --once --dry-run
./gather_news.sh collect --once
./gather_news.sh health
./gather_news.sh export \
  --since 2026-09-07T00:00:00Z \
  --until 2026-09-08T00:00:00Z \
  --output exports/2026-09-07 \
  --dry-run
```

Use `--source ID` only when the user asks for a source-limited collection. The seventeen enabled sources are `nytimes`, `ft`, `borsen`, `politiken`, `berlingske`, `dr`, `tv2`, `jp`, `information`, `altinget`, `kristeligt_dagblad`, `via_ritzau`, `bbc`, `economist`, `guardian`, `wapo`, and `wsj`; `validate-config` lists them. Collection coverage always means items observed in configured feeds while the collector ran.

Preview mutating actions with `--dry-run`. Export and backup targets are immutable: choose a new path rather than deleting or overwriting an existing one. A partial collection is a successful call whose `result.status` is `partial` and reports only failure counts; run `health`, whose `reasons` list names each feed that has failed three consecutive polls as `feed_failures:<feed_id>` and whose `feeds` rows carry `last_error_json`, before deciding whether its data is fit for export. Retry `lock_busy`, `timeout`, or a transient `upstream_error` cautiously. Fix `invalid_arguments`, `resource_not_found`, and `conflict` before retrying.

## Invariants that guide every change

- RSS sightings and compressed raw payloads are facts; `articles` is a rebuildable projection.
- Keep ingestion deterministic and model-free. Cross-source clustering, relevance scoring, and summaries belong downstream.
- Preserve exact publisher URLs in `raw_url`; canonical cleanup must follow source rules.
- Advance feed validators only with committed parsed data; a valid `304` records the check without touching them.
- Isolate feed failures, keep SQL behind `db.py`, and order every deterministic result explicitly.
- Never fetch NYT article pages or add browser/login/paywall automation.
- Preserve unrelated worktree changes and never test against `var/news-ingest.sqlite3`.

## Load details only when needed

- Daily operations, scheduling, all actions, dry-runs, backups, errors, and fixture capture: [references/operations.md](references/operations.md)
- Code layout, change workflow, testing, CLI evolution, and dependency boundaries: [references/development.md](references/development.md)
- Source identities, prominence, transactions, exports, replay, and data safety: [references/contracts.md](references/contracts.md)

For a requirement not covered there, read `ingest/AGENTS.md`, then the authoritative `docs/ingest-architecture.md` at the repository root. Treat the plan's optional work packages 14 and 15 as gated scope requiring explicit user approval.
