# copenhagen-today

A personal daily newspaper: first-party RSS feeds in, one edited edition out, published as a static
broadsheet website and a one-page grayscale image for a TRMNL X panel.

| Directory | What it is |
|---|---|
| `ingest/` | Block 1. Deterministic RSS collector and exporter. See `ingest/README.md`. |
| `editorial/` | Block 2. Editorial desk. Reserved; not yet built. |
| `publisher/` | Block 3. Web and device publisher. Planned; not yet built. |
| `plans/` | Architecture, implementation plans, decision log, roadmap, and design mockups. |
| `skills/` | Repository-level agent skills. |

The blocks share no code. Block 1 hands block 2 an immutable export bundle; block 2 hands block 3
an immutable edition JSON validated against block 3's published schema; block 3 returns a
publication receipt.
