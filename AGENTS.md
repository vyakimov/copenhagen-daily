# AGENTS.md

`copenhagen-daily` is a personal newspaper built from first-party RSS feeds. It is three
independently runnable blocks in sibling directories, communicating only through shell wrappers,
JSON envelopes on stdout, and files on disk. Nothing imports across a block boundary at runtime.

| Directory | Block | Status |
|---|---|---|
| `ingest/` | Block 1: deterministic RSS collection and immutable JSONL exports (Python) | Built. Rules in `ingest/AGENTS.md`. |
| `editorial/` | Block 2: editorial desk producing one edition per run (a Claude Code session under a skill, a Codex checker session, and deterministic Python tools) | Built and scheduled: six launchd jobs in `editorial/config/launchd/` collect, check tomorrow's logins at 22:00, run the edition at 05:30, verify the live site, retry, and check freshness; see `editorial/OPERATIONS.md`. Design in `docs/editorial-architecture.md`. |
| `publisher/` | Block 3: web edition and TRMNL device page from an accepted edition (TypeScript, Astro, Playwright) | Built: web, store, and a single-composition device page, rendered on every publish and pushed to the kitchen screen. Spec in `docs/publisher-architecture.md`. |

Cross-block documents live in `docs/` (`editorial-architecture.md`, `ingest-architecture.md`,
`publisher-architecture.md`, `aws-delivery.md`, `decision-log.md`, `roadmap.md`, `design/`,
`reviews/`). Repository-level agent skills live in `skills/`.

## Boundaries that hold across the whole repository

- `ingest/` must never depend on a browser, a language model, a credential, or the Node toolchain.
  Its own `AGENTS.md` is authoritative inside that directory and is not relaxed by anything here.
- `publisher/` may use Node and a pinned headless Chromium, but only to render pages it generated
  itself from local assets. It never visits a publisher URL, loads a remote resource, or calls a model.
- `editorial/` is the only block that calls a language model, and it does so only inside bounded
  sessions of three kinds. The desk session runs Claude Code with `--permission-mode acceptEdits`, no
  web tools, no MCP servers, and a Bash allowlist of two wrapper actions (`check-clusters`, `score`)
  that write inside the run directory; it clusters and selects and writes no copy. One writer session
  per story runs Claude Code with the Read tool only, in a working directory that holds that story's
  brief and nothing else, with no other directory added, so a read anywhere else is refused; it
  answers with that story's copy. The checker runs `codex exec -s read-only`, a read-only
  sandbox that can still run shell commands; when the checker is Claude, Bash is disallowed. No
  session has a browser, network tools, or credentials, and after every session the runner refuses to
  go on if the session wrote outside the run directory (`stray_edits`) or changed the runner's own
  inputs (`input_modified`, with the run's files quarantined). The deterministic runner around them
  holds the one delivery credential (a scoped IAM user), never the sessions; the only secret a session receives is the one credential it needs to call the model, the claude.ai token or, as a fallback, the API key (`editorial/OPERATIONS.md`, "The desk's own login"); the codex checker runs on its own login, the ChatGPT one or, as a fallback, a codex home logged in with its API key, and is handed nothing of Claude's. The runner
  alone fetches the Wikipedia summaries that verify a writer's explanation of a name or term.
- Every block exposes one self-locating POSIX `sh` wrapper (`ingest/gather_news.sh`,
  `editorial/edit_news.sh`, `publisher/publish_news.sh`) that emits exactly one JSON object on stdout and diagnostics on stderr.
  Use the wrapper; do not invoke `uv`, `npm`, `node`, or `astro` directly for routine work.
- Published exports, editions, and bundles are immutable and atomically renamed into place. Never
  overwrite one.
- Each block keeps its own lockfile and runtime state (`<block>/var/`, gitignored). No block claims
  the repository root.
