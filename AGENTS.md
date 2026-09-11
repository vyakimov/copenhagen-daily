# AGENTS.md

`copenhagen-today` is a personal newspaper built from first-party RSS feeds. It is three
independently runnable blocks in sibling directories, communicating only through shell wrappers,
JSON envelopes on stdout, and files on disk. Nothing imports across a block boundary at runtime.

| Directory | Block | Status |
|---|---|---|
| `ingest/` | Block 1: deterministic RSS collection and immutable JSONL exports (Python) | Built. Rules in `ingest/AGENTS.md`. |
| `editorial/` | Block 2: LLM editorial desk producing one edition per run (Python) | Reserved. Design in `plans/news-editorial-architecture-plan.md`. |
| `publisher/` | Block 3: web edition and TRMNL device page from an accepted edition (TypeScript, Astro, Playwright) | Planned. Spec in `plans/news-publishing-implementation-plan.md`. |

Cross-block documents live in `plans/`. Repository-level agent skills live in `skills/`.

## Boundaries that hold across the whole repository

- `ingest/` must never depend on a browser, a language model, a credential, or the Node toolchain.
  Its own `AGENTS.md` is authoritative inside that directory and is not relaxed by anything here.
- `publisher/` may use Node and a pinned headless Chromium, but only to render pages it generated
  itself from local assets. It never visits a publisher URL, loads a remote resource, or calls a model.
- `editorial/` is the only block that calls a language model. It has no browser, shell, or
  publishing credentials.
- Every block exposes one self-locating POSIX `sh` wrapper (`ingest/gather_news.sh`,
  `publisher/publish_news.sh`) that emits exactly one JSON object on stdout and diagnostics on stderr.
  Use the wrapper; do not invoke `uv`, `npm`, `node`, or `astro` directly for routine work.
- Published exports, editions, and bundles are immutable and atomically renamed into place. Never
  overwrite one.
- Each block keeps its own lockfile and runtime state (`<block>/var/`, gitignored). No block claims
  the repository root.
