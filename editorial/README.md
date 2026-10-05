# Block 2: the editorial desk

The desk that turns a block 1 export into one edition for block 3. The editor is a Claude Code
session under `skills/editorial-desk`; the checker is a second session under `editorial/VERIFIER.md`;
the rules are deterministic tools behind `edit_news.sh`. The design is
`docs/editorial-architecture.md`.

## One executable

```sh
./edit_news.sh list-actions
./edit_news.sh run --dry-run                 # today's edition: inputs, collect, window, memory, editor, check, preflight, publish --dry-run
./edit_news.sh run                           # reconcile, inputs, collect, window, memory, editor, check, preflight, publish, receipt, threads, deliver, archive
./edit_news.sh run [--cutoff <RFC 3339 UTC>] [--edition <id>] [--publish-root <dir>] [--no-collect] [--checker claude|codex] [--retry]
./edit_news.sh status
./edit_news.sh window --run runs/<id> --cutoff 2026-09-24T03:30:00Z [--previous-cutoff <ts>] [--bundle <dir>] [--feeds <file>]
./edit_news.sh memory --run runs/<id> --publish-root ../publisher/var/evaluation/site [--registry <file>]
./edit_news.sh check-clusters --run runs/<id>
./edit_news.sh score --run runs/<id>
./edit_news.sh build --run runs/<id> [--spec <file>] [--output <file>]
./edit_news.sh apply-verdicts --run runs/<id> [--edition <file>] [--verdicts <file>] [--output <file>] [--final]
./edit_news.sh deliver [--publish-root <dir>]
./edit_news.sh freshness [--publish-root <dir>] [--max-age-hours <n>] [--notify]
./edit_news.sh verify-live [--publish-root <dir>] [--site-url <url>] [--fix] [--notify]
```

The cutoff is 05:30 Copenhagen time (03:30Z in summer, 04:30Z in winter); `run` derives today's from
`policy.yaml`. `--retry` skips a run whose edition already ended as published, dry run, or skipped.

Every call emits exactly one JSON object on stdout; diagnostics go to stderr. Exit 0 is success,
2 malformed arguments, 1 a well-formed action that failed. Provision `.venv` once from `uv.lock`
(`uv sync --frozen`); the wrapper finds it itself. See [OPERATIONS.md](OPERATIONS.md) for the
schedule and what to do when a run fails.

## What is here

- `policy.yaml`: the masthead's standing line: scoring publishers, section table, section weights,
  kicker vocabulary, budgets, limits, schedule. Read at every run.
- `HANDBOOK.md`: the working method for the editor, person or model, and the hard rules.
- `STYLE.md`: spelling, numbers, time, names, and attribution forms, drafted from the first editions.
- `VERIFIER.md`: the checker's brief, tool-agnostic.
- `config/desk.yaml`: where block 3's publish root is, which tools and models run the sessions
  (`checker`, `editor_model`), whether the device page is rendered (`device`), the AWS `delivery` settings, how the owner is told (`notify`), and
  `max_edition_age_hours` for the freshness check.
- `contracts/`: the spec schema and the verdicts schema, the two files the sessions must satisfy.
- `runs/<edition-id>/`: one directory per run, the editorial record. The small files are committed
  after an activated publish; the bundle, the window, and the session records stay on disk.
- `examples/2026-09-15-morning/`: the golden example, an edition the owner judged good, with the
  compact editorial spec, the accepted contract, the coverage inventory, and notes on every decision.
  `examples/build_edition.py` rebuilds it through the wrapper.
- `src/news_editorial/`: the tools. `tests/` runs against a cut of the 15 September bundle and a
  two-edition publish root under `tests/fixtures/`.
