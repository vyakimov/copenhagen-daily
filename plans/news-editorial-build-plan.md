# Building block 2: a plan for the person doing it

Status: build plan, 24 September 2026. This document is written for the owner, in the same spirit as
the [AWS plan](aws-plan.md): it says what to build, in what order, and why, and stops short of the
detail the implementing plans carry. The [editorial architecture](news-editorial-architecture-plan.md)
remains authoritative on what block 2 must do; the [desk handbook](../editorial/HANDBOOK.md) holds the
working method and the hard rules; the [policy file](../editorial/policy.yaml) holds the numbers. This
plan is about how block 2 is put together on this branch. A second implementation, a Python application
calling the model API directly, is being built by hand on `main` as a learning exercise and is not
described here.

## What block 2 is

A scheduled run that turns one of block 1's export bundles into one edition contract for block 3. It
clusters articles into events, scores and selects under the written policy, writes each selected story
from attributed evidence, has the copy checked, and publishes through block 3. It is an editorial desk,
not an agent: the sequence of steps is fixed, every step ends in a file, and a model decides what the
paper says, never what the system does next.

**The editor is a Claude Code session running under a skill.** The two editions the owner judged good,
15 September morning and 19 September evening, were produced exactly this way: a session read the
handbook, the policy, the golden example, and the bundle, wrote a compact spec, and ran the reference
tool that resolves the spec into a contract. Block 2 makes that repeatable without a person present.
The quality came from the documents the session read, so those documents stay the thing the owner edits
when an edition reads badly, and the code around the session is small.

## The split: judgement in the session, rules in code

The architecture divides the work into what a model decides and what code decides. That division does
not move. What moves is the mechanism: the model's part becomes the session reading and writing files,
and code's part becomes a set of small command-line tools the session must call rather than reason
about. The session never computes a score, resolves a source, or validates a contract in its head.

The tools, all actions of one wrapper, `editorial/edit_news.sh`, emitting one JSON object on stdout
like the other two blocks:

| Action | What it does | Model involved |
|---|---|---|
| `window` | Runs block 1's export for the 72-hour publication window ending at the cutoff, admitting anything newly observed since the previous edition, verifies the bundle's hashes and counts, numbers the articles `1..N`, attaches sections from the policy's feed table and the scoring or linked status of each publisher, and writes `window.json`. The session reads this file and never the raw JSONL. | No |
| `memory` | Reads the activated editions of the last fortnight from block 3's store, newest first, and writes `memory.json`: every published story id with the articles it carried, the active threads with their last-seen date, and the day each ran. | No |
| `check-clusters` | Validates the session's `clusters.json`: every number exists and appears at most once, members fall inside a plausible time span, grouped articles share a rare term, entity, or section, no cluster is implausibly large. A failing cluster is split back into singletons and the split is recorded. | No |
| `score` | Computes the visible formula for every validated cluster: breadth among scoring publishers, peak prominence on ranked surfaces only, recency in editions, thread strength, the section multiplier. Applies eligibility, repeat suppression against memory, and the diversity rules. Writes `ranking.json` with every term shown and a decision reason on every candidate. | No |
| `build` | Today's `examples/build_edition.py`, promoted: turns `spec.json` into `edition.json` with every source resolved from the bundle by identity, and refuses a paragraph that cites a publisher not among its sources. | No |
| `apply-verdicts` | Applies the verifier's `verdicts.json` to `edition.json`: strikes unsupported sentences, decides per story whether it still stands, and writes the result and a list of stories to send back. | No |
| `run` | The whole sequence below, with limits, for one edition. | Invokes the editor and the verifier |
| `status` | The state of the most recent run. | No |

Numbering the window is deliberate. The session refers to articles by small integers in every file it
writes, and the tools map them back to `(source, source_id)`. Long identifiers are where a model
mistranscribes, and an unknown number is a validation failure rather than a silent loss.

## One run, files between phases

A run owns `editorial/runs/<edition-id>/` and fills it in a fixed order. Each phase reads the files
before it and writes one file. The phase files are what make a run resumable, what the verifier checks
without seeing the editor's reasoning, and what the owner reads afterwards.

| Order | File | Written by | Content |
|---|---|---|---|
| 1 | `window.json` | `window` | The numbered candidate window with sections and publisher status |
| 2 | `memory.json` | `memory` | Covered stories, threads, and edition days from block 3's store |
| 3 | `clusters.json` | editor | Groups with an event description, member numbers, confidence, and thread attachment; anything unmentioned is a singleton |
| 4 | `ranking.json` | `score` | Every cluster with its terms, eligibility, and decision reason |
| 5 | `selection.json` | editor | The stories to write with role, device participation, kicker, and the reason for any departure from the ranking |
| 6 | `spec.json` | editor | The compact editorial decision: copy variants, callouts, and source references per story, in the form the golden example uses |
| 7 | `edition.json` | `build` | The contract, validated against block 3's schema |
| 8 | `verdicts.json` | verifier | Per sentence: supported with the passage, or unsupported with the reason |
| 9 | `fit-*.json` | block 3 | Fit reports, one per attempt |
| 10 | `NOTES.md` | editor | The editorial log entry: what led and why, what was rejected and why, anything that felt wrong |
| 11 | `status.json` | `run` | Outcome, timings, limits hit, receipt |

The whole window fits in one context, so clustering stays one reading pass, as the architecture
requires. Writing fans out: the editor delegates each selected story to a subagent that receives only
that story's evidence packet, its role and word budget, and the writing guidelines, and returns the
story's part of the spec. This keeps the main context clean and matches the plan's one-call-per-story
shape. The main session then assembles the spec, writes the edition-level fields, and runs `build`.

Retention is the run directory. The small files are committed after publication, as the archived runs
already are. `window.json` stays on disk beside them, gitignored, and the edition carries the bundle's
identity and digest, so an edition can always be traced to exactly what it read. Reproducibility means
this retention, not a promise that a fresh session would decide the same way.

## Verification is a separate invocation with a file contract

The verifier is a second session with different context and a different brief. It receives
`edition.json` and `window.json` and nothing else: not the spec, not the notes, not the editor's
reasoning. It writes `verdicts.json`. Because the interface is two files in and one file out, the
verifier is swappable, and running it on a different model is a genuine advantage: a different model has
different blind spots, which is the property wanted in a checker. The verifier's brief therefore lives
in a plain file, `editorial/VERIFIER.md`, that any tool can read, with a thin Claude Code skill pointing
at it for the Claude case and a Codex invocation reading it directly for the Codex case.

What the verifier checks is the list the architecture gives: unsupported statements, changed attribution,
contradictions with the sources, a paraphrase presented as a quotation, a quotation without a speaker.
It also notes departures from the writing guidelines, which are advisory for the editorial log and
never strikes. It marks; it does not rewrite. The repair rule is in the handbook: strikes are applied by code, a story
that no longer stands goes back to the editor once with the strikes attached, and a story that fails
again falls to a headline with a link.

## The runner and the schedule

One shell action, `edit_news.sh run`, does the deterministic sequence: block 1 collect and export, the
editor invocation, `build`, the verifier invocation, `apply-verdicts`, one send-back if needed, block
3's `validate` and `fit`, the bounded fit repair, `publish`, the receipt check, and the commit of the run
directory. launchd invokes it on the Mac at the cutoff in `Europe/Copenhagen`; cron on the AWS box does
the same later. Nothing else schedules anything.

The editor runs headless with a restricted tool allowlist: the desk tools as the only shell command,
file edits accepted without prompting, the repository readable, and no web fetch, no browser, no other
shell. That is the boundary `AGENTS.md` states, enforced by the invocation rather than by trust. The
one thing the invocation cannot narrow is where inside the repository the session may write; the skill
confines it to the run directory, and a stray edit anywhere else shows in git before the run's commit. The invocation is
bounded by a maximum turn count and a wall clock from the policy's `limits`. The verifier gets the same
shape with a smaller budget.

Failure is loud and final within a run. If any step fails or a limit is hit, the runner writes
`status.json`, stops, and leaves the last activated edition in place with its own date. Nothing retries
a model step blindly, because a second attempt at the same window costs the same as the first and hides
the fault. The owner reads the status and decides. A headlines-only degraded edition is designed in the
[roadmap](roadmap.md) and is not in release 1.

The fit loop mirrors a desk: block 3 names the slot and the shortfall, the editor is asked for the
specific shorter variant the handbook's repair order calls for, and the loop stops when `fit` passes or
after the bounded number of rounds, after which the remaining repair is participation only. The golden
example needed three rounds by hand, which is what the bound is calibrated to. Variants are written on
demand, not speculatively, because most editions need few of them.

## What protects quality across fresh runs

- **Two schemas the session cannot argue with.** `spec.json` gets its own JSON Schema, and `build`
  refuses a spec that fails it. Block 3 validates the contract. A malformed edition fails before
  publication, whatever the session believed it wrote.
- **Citation integrity in code.** `build` refuses a paragraph citing a publisher not among the story's
  sources, and the source list is resolved from evidence, so a URL, a timestamp, or a hash can never be
  invented.
- **The formula is computed, not recalled.** `score` writes every term, and `selection.json` must give
  a reason for any departure from the ranking. The editor may overrule the numbers, as the handbook
  allows, but the overruling is a recorded sentence, not a silent reordering.
- **The editorial log is the feedback loop.** The owner reads `NOTES.md`. When something is wrong the
  fix is an edit to the handbook, the style guide, or the policy, committed, which is the correction
  mechanism the architecture prescribes. No weights adjust themselves.
- **Every run is a golden candidate.** A run the owner judges good moves from `runs/` to `examples/`.
  The golden set grows from real editions without separate labelling work; more of them is on the
  roadmap.
- **Source text is data.** The desk skill says so in one sentence, and the allowlist makes it true: a
  feed description that reads as an instruction can change nothing outside the run directory.

## Build order

Each package ends with a check the owner can show. Later packages depend on earlier ones.

1. **`window`, `memory`, `score`, `check-clusters`.** The deterministic tools, with the 15 September
   bundle as the test fixture and the golden example's clusters and selection as the expected output.
   The wrapper, the JSON envelope, the process lock, and a separate SQLite file for block 2's own state,
   in block 1's style. You learn: the two clocks, the formula as code, the validator as the place where
   the cheap signal lives.
2. **`build` and the spec schema.** Promote the reference builder, write the schema for the spec, and
   make the golden examples round-trip: spec in, the archived contract out, byte for byte.
3. **The desk skill.** `skills/editorial-desk/SKILL.md`: the run as numbered steps, each ending in a
   file, referencing the handbook, the policy, the style guide, and the golden examples rather than
   repeating them. Produce one edition by hand through the skill and compare it with the golden
   example. This is the package where the quality either holds or does not, and it is tested by
   reading, not by pytest.
4. **The verifier.** `editorial/VERIFIER.md`, the verdicts schema, and `apply-verdicts`. Run it on the
   two golden editions, which should pass clean, and on a copy with three seeded errors, which it must
   catch. Try it on Codex as well as Claude and keep whichever catches more of the seeded set.
5. **The runner.** `run` with the headless invocations, the allowlist, the limits, `status.json`, and
   the launchd job. Kill a run midway and confirm the last edition stays activated and the status says
   why.
6. **The repair loops.** The verification send-back and the fit rounds, each bounded, each recorded in
   the run directory. Reproduce the golden example's three-round fit by replaying its first contract.

After package 6 the paper publishes itself every morning. The style guide, `STYLE.md`, is still to be
written and should be written from the editorial log's first fortnight of complaints rather than in
advance.

## What this design gives up

Structured outputs, prompt caching control, per-edition token accounting, and a pinned prompt revision
all belong to the API path and are not available here. A session run is priced by the subscription, not
per token, and its variance between runs is higher than a pipeline with fixed prompts. That is why the
phase files, the schemas, and the independent verifier carry more weight in this design than they
would there. The Python that remains is the six tools and their tests, which is smaller and easier to
keep working than an application that owns the model calls.
