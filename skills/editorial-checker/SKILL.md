---
name: editorial-checker
description: Check one edition of Copenhagen Daily sentence by sentence against its evidence and write verdicts.json. Use when asked to check, verify, or review an edition in a run directory. Never rewrites copy.
---

# The editorial checker

Read `editorial/VERIFIER.md` and follow it exactly. The run directory is given to you as an
absolute path; read `check-input.json` there and nothing else in the run, and write your verdicts to
`verdicts.json` in the same directory as a single JSON document matching
`editorial/contracts/verdicts.v1.schema.json`. Do not read `spec.json`, `NOTES.md`, or
`selection.json`: the check is independent of the editor's reasoning. Do not modify any other file.
