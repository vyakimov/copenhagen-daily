# copenhagen-daily

[![check](https://github.com/vyakimov/copenhagen-daily/actions/workflows/check.yml/badge.svg?branch=deploy)](https://github.com/vyakimov/copenhagen-daily/actions/workflows/check.yml)

A personal daily newspaper: first-party RSS feeds in, one edited edition out, published as a static
broadsheet website and a one-page grayscale image for a TRMNL X panel.

| Directory | What it is |
|---|---|
| `ingest/` | Block 1. Deterministic RSS collector and exporter. See `ingest/README.md`. |
| `editorial/` | Block 2. Editorial desk: `policy.yaml`, `HANDBOOK.md`, a golden example edition, and the runner that produces one edition a day under launchd. See `editorial/README.md`. |
| `publisher/` | Block 3. Web and device publisher. See `publisher/README.md`. |
| `docs/` | Architecture documents, AWS delivery, decision log, roadmap, design mockups, and reviews. |
| `skills/` | Repository-level agent skills. |

The blocks share no code. Block 1 hands block 2 an immutable export bundle; block 2 hands block 3
an immutable edition JSON validated against block 3's published schema; block 3 returns a
publication receipt.

## Licence

The code and documentation are licensed under the Apache License, Version 2.0 (see `LICENSE`). The
editions in `editorial/runs/` and `editorial/examples/` are the paper's own copy and are not part of
the licence; headlines and short excerpts from the publishers' feeds that appear in fixtures and run
records remain their publishers' property and are reproduced only as citations.
