# Development reference

Read this file when changing code, configuration, migrations, tests, or the CLI.

## Repository map

| Area | Ownership |
|---|---|
| `config/sources.yaml` | Publisher/feed behavior, priorities, URLs, gates, and runtime paths. Do not create publisher adapter modules. |
| `src/news_ingest/models.py` | Strict boundary models; unknown fields are rejected. |
| `feed.py`, `identity.py`, `urls.py`, `time.py`, `merge.py`, `hashing.py`, `prominence.py`, `sighting_content.py` | Pure normalization, projection, and sighting-content factoring rules where possible. |
| `db.py` and `migrations/` | All SQL, forward-only numbered schema migrations (001 to 005), transactions, the merge-state cache, rebuild, and content deduplication. |
| `collect.py`, `export.py`, `health.py`, `replay.py`, `fixture.py` | Orchestration at narrow boundaries. |
| `tools/` | `benchmark_collect.py` (run through `benchmark-collect`; temporary databases only) and the `capture_fixture.py` compatibility shim. |
| `cli.py` | JSON action catalog, strict argument parsing, stable envelopes, error mapping, and offline verification. |
| `gather_news.sh` | Sole allowlisted executable; resolves repository and `.venv`, then replaces itself with the Python module. |
| `tests/` | Network-free default suite using temporary databases and directories. |

Read `AGENTS.md` before editing. For subtle product behavior, search the implementation plan by topic instead of loading all of it. Preserve the architecture: Python 3.12+, `src/` layout, standard SQLite, no ORM/web framework/queue, configuration-driven publishers, and no LLM in ingestion.

## Change workflow

1. Inspect `git status` and preserve unrelated changes.
2. Locate behavior with `rg`; read the relevant pure function, database API, and nearby tests.
3. Make the smallest coherent change. Schema changes need a new numbered, forward-only migration.
4. Add table-driven normalization cases or a regression test for an actual defect. Default tests cannot access the network or real runtime database.
5. Run the complete supported check:

```sh
./gather_news.sh check
```

This action runs config validation, Ruff check, Ruff format check, compileall,
`pytest -m "not live" -q`, and shell syntax validation for the wrapper. It
assumes the operator-provisioned `.venv` already matches `uv.lock`; it never
invokes `uv` and cannot install or update dependencies.

For persistence, collection, recovery, or export changes, add the smallest relevant CLI smoke test using a temporary database/output. Exercise it through `gather_news.sh`; never point a test at `var/news-ingest.sqlite3`.

## CLI contract

Treat the CLI as an API for agents:

- One JSON object on stdout for success, action failure, usage failure, and unexpected exceptions. Help text is the sole exception.
- Stable top-level `ok`, `action`, `result|error`, and `meta`; versions live in `meta`.
- Usage errors exit `2`; other failures exit `1`; successes exit `0`.
- Error types are stable snake_case. Messages tell the caller what to fix; details include valid values or the failed check where helpful.
- `list-actions` is sorted and JSON-Schema-like. Update it and action help whenever flags change.
- Mutating actions have a real dry-run that performs validation but no network/database/output mutation.
- Keep list output bounded or summarized. Put volatile/request details in `meta` when introduced.
- Never prompt, use color/spinners/pagers, or read stdin. The only subprocesses are the fixed verification steps `check` runs (Ruff check and format, compileall, pytest, and `sh -n` on the wrapper), each with a 300-second timeout; do not add others.
- Use fixed timeouts for subprocess and network boundaries. Keep upstream/raw data out of the top-level envelope.
- Evolve the schema additively within a major version. Bump `meta.schema_version` for a breaking contract change.

The legacy `news-ingest` package entrypoint may remain for packaging compatibility, but documentation, schedulers, tests run by agents, and operational examples must use `gather_news.sh`.

## Dependency boundary

Direct dependencies remain exactly pinned in `pyproject.toml`, with `uv.lock` committed. The wrapper deliberately does not expose dependency installation or arbitrary Python execution. If a change truly needs a dependency update, prepare the source/config changes and tell the operator that lockfile provisioning requires a separately controlled dependency-management step. Do not quietly use a system interpreter or add a download path to the wrapper.

## Logging and secrets

Stdout is the CLI contract and the only output the package writes; there is no logging framework and no stderr diagnostics. Errors are stored as JSON in `feed_polls.error_json`, `feed_state.last_error_json`, and quarantine rows. The configuration holds no credentials and no environment interpolation exists. If logging is ever added, it must not write raw payloads, full descriptions/bodies, cookies, authorization headers, API keys, or credentials, and URL diagnostics would need redaction of any secret parameters; neither mechanism exists today.

Configuration is parsed with `yaml.safe_load` and validated before mutation/network access. URLs must be HTTPS; feed IDs, URLs, and per-source orders must be unique; runtime database/lock paths must remain inside the repository runtime root.
