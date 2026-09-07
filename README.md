# news-ingest

`news-ingest` is a small, portable Python service that records every valid item observed in configured first-party RSS feeds from NYT, FT, Børsen, Politiken, and DR. It stores raw feed payloads, feed sightings, and a rebuildable article projection, then atomically exports deterministic JSONL bundles.

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

```sh
uv sync --locked
uv run news-ingest validate-config
uv run news-ingest collect --once
uv run news-ingest health
uv run news-ingest export --since 2026-01-01T00:00:00.000000Z --until 2027-01-01T00:00:00.000000Z --format jsonl --output exports/initial
```

See `docs/operations.md` and `docs/scheduling.md` for operations and scheduling.
