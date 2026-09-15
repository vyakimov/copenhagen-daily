# Block 2: the editorial desk

The desk that turns a block 1 export into one edition for block 3. The Python application is not yet
built; its design is `plans/news-editorial-architecture-plan.md` and the owner's build plan is
`plans/news-editorial-build-plan.md`. What is here already:

- `policy.yaml`: the masthead's standing line: scoring publishers, section table, section weights,
  kicker vocabulary, budgets, schedule. Read at every run.
- `HANDBOOK.md`: the working method for the editor, person or model.
- `examples/2026-09-15-morning/`: the golden example, an edition the owner judged good, with the
  compact editorial spec, the accepted contract, the coverage inventory, and notes on every decision.
- `examples/build_edition.py`: the reference tool that turns a spec into a contract by resolving
  sources from the bundle. Block 2 proper replaces it.
