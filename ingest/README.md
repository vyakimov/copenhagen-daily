# news-ingest

`news-ingest` is a small, portable Python service that records every valid item observed in configured first-party RSS feeds from NYT, FT, Børsen, Politiken, Berlingske, DR, TV 2, Jyllands-Posten, Information, Altinget, Kristeligt Dagblad, BBC News, The Economist, The Guardian, The Washington Post, and The Wall Street Journal. It stores raw feed payloads, feed sightings, and a rebuildable article projection, then atomically exports deterministic JSONL bundles.

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
./gather_news.sh export --since 2026-01-01T00:00:00.000000Z --until 2027-01-01T00:00:00.000000Z --output exports/initial --dry-run
```

Repeat a mutating command without `--dry-run` only after reviewing its plan.
Use `./gather_news.sh check` for the complete offline repository verification.

The project-local agent skill is
[`skills/news-gatherer/SKILL.md`](../skills/news-gatherer/SKILL.md) at the repository root. Its short main
file covers daily use; optional references hold operations, development, and
data-contract details.

See `docs/operations.md` and `docs/scheduling.md` for operations and scheduling.
