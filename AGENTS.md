# AGENTS.md

`copenhagen-daily` is a personal newspaper built from first-party RSS feeds. It is three
independently runnable blocks in sibling directories, communicating only through shell wrappers,
JSON envelopes on stdout, and files on disk. Nothing imports across a block boundary at runtime.

| Directory | Block | Status |
|---|---|---|
| `ingest/` | Block 1: deterministic RSS collection and immutable JSONL exports (Python) | Built. Rules in `ingest/AGENTS.md`. |
| `editorial/` | Block 2: editorial desk producing one edition per run (a Claude Code session under a skill, with deterministic Python tools) | Built and rehearsed end to end on 24 September 2026 (dry run with a send-back and a fit-repair round). The launchd job in `editorial/config/` is not yet installed; see `editorial/OPERATIONS.md`. Design in `plans/news-editorial-architecture-plan.md`, build plan in `plans/news-editorial-build-plan.md`. |
| `publisher/` | Block 3: web edition and TRMNL device page from an accepted edition (TypeScript, Astro, Playwright) | Built: web, store, and a single-composition device page. Spec in `plans/news-publishing-implementation-plan.md`. |

Cross-block documents live in `plans/`. Repository-level agent skills live in `skills/`.

## Boundaries that hold across the whole repository

- `ingest/` must never depend on a browser, a language model, a credential, or the Node toolchain.
  Its own `AGENTS.md` is authoritative inside that directory and is not relaxed by anything here.
- `publisher/` may use Node and a pinned headless Chromium, but only to render pages it generated
  itself from local assets. It never visits a publisher URL, loads a remote resource, or calls a model.
- `editorial/` is the only block that calls a language model, and it does so only inside two bounded
  sessions whose tools are the desk's own read-only actions; the model sessions have no browser, no
  general shell, and no credentials. The deterministic runner around them holds the one delivery
  credential (a scoped IAM user) and the NAS host alias, never the sessions.
- Every block exposes one self-locating POSIX `sh` wrapper (`ingest/gather_news.sh`,
  `editorial/edit_news.sh`, `publisher/publish_news.sh`) that emits exactly one JSON object on stdout and diagnostics on stderr.
  Use the wrapper; do not invoke `uv`, `npm`, `node`, or `astro` directly for routine work.
- Published exports, editions, and bundles are immutable and atomically renamed into place. Never
  overwrite one.
- Each block keeps its own lockfile and runtime state (`<block>/var/`, gitignored). No block claims
  the repository root.
