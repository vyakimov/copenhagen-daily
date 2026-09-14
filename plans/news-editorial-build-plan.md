# Building block 2: a plan for the person doing it

Status: build plan, 14 September 2026. This document is different in kind from the other plans in
this directory. Those are written for an implementing agent and are deliberately exhaustive, so that a
capable agent can hand them to a less capable one. This one is written for the owner, who is building
block 2 by hand, partly to learn and partly to have something worth explaining in an interview. It
says what to build, in what order, and why each choice was made, and it stops short of the detail the
other plans carry. The [editorial architecture](news-editorial-architecture-plan.md) remains
authoritative on what block 2 must do; this plan is about how to go about doing it.

## What block 2 is

A scheduled Python batch that turns one of block 1's export bundles into one edition contract for
block 3. It clusters articles into events with one model call, scores and selects under a written
policy in ordinary code, writes each selected story from attributed evidence, checks the writing, and
publishes through block 3. It is an editorial desk, not an agent: there is no loop in which a model
decides what to do next. Keeping that in mind settles most of the technology questions below.

## The stack, and why

**Pydantic v2 is the spine.** Block 1 already uses it and the house style should not change between
blocks. The edition contract's models are generated from block 3's hand-written JSON Schema with
`datamodel-code-generator`, so the Python side cannot drift from the TypeScript side; a schema change
in block 3 is a regeneration here, not a rewrite. Every model response is parsed into a Pydantic model
through structured outputs, which means every malformed response is a typed validation error you can
log, count, and test against rather than a string you have to inspect.

**LangGraph orchestrates; LangChain does not.** LangChain as an abstraction layer over models and
prompts is the one name on the usual list that senior interviewers increasingly treat as a warning
sign, because it hides the parts of the problem they want to hear you understand. LangGraph is a
different tool: an explicit state graph with checkpointing. The plan's stages (import, cluster, select,
write, verify, publish) are that graph, and the requirement to resume an interrupted run from retained
inputs is exactly what its SQLite checkpointer provides. Its interrupt mechanism is also how a human
override, a pinned story or an edited headline, would enter later without breaking the immutability of
generated output. Use it for the graph and nothing else. The sentence for the interview is: "I used a
state graph for durable, resumable stages, and kept the model calls on the plain SDK so nothing was
hidden."

**The Anthropic SDK directly for model calls.** Block 2 makes four kinds of call: cluster and thread the
candidate window, assess relevance for the clusters that survive, write one story, and check one story
for unsupported claims. None of them is an agent loop, so a framework between you and the API would
only obscure prompt caching, structured outputs, token accounting, and retries, which are the things
worth learning. Pydantic AI is the respectable alternative if a second framework name matters to you;
do not use both.

**SQLite with explicit SQL and forward-only migrations.** As block 1 does it. Consistency across the
three blocks is itself something to point at: one storage discipline, one migration style, one JSON
envelope on stdout, one process lock. A separate database file from block 1, never a shared one.

**No vector store, no embeddings.** The architecture plan argues this at length: a single model call
over the whole window is cheaper and less fragile than a retrieval stage with thresholds to tune. Being
able to say why you did not add a vector database is worth more than having added one.

## Where the boundaries are, and how they are crossed

Block 2 calls block 1 by running `gather_news.sh export` as a subprocess and parsing the JSON envelope.
It calls block 3's `validate` as preflight and `publish` to release, the same way. These paths are
deterministic and must never involve a model, so exposing them to a model as tools would be the wrong
shape: a tool call is for a decision, and there is no decision here.

Where MCP does belong is above the pipeline. A small MCP server that exposes the operational commands
of all three blocks (health, dry runs, a re-export, a receipt lookup, the editorial log) lets an operator
work with the system from Claude Code in conversation. That is MCP in the role it was designed for,
and it puts the name on your CV without putting a model in the reliability path. Build it last, when
there is something to operate.

## What will actually impress an interviewer

Not the framework names. These, each of which the architecture plan already requires:

- **Evidence-bound generation.** Every sentence of copy cites publisher ids, code checks each id
  against the story's sources, and a bounded second model pass hunts for claims the evidence does not
  support. The failure mode is a shorter story, never an invented one.
- **Deterministic replay.** Every accepted model response is stored with its exact inputs and prompt
  revision, so an edition can be rebuilt without a model call. Reproducibility means retention, not
  temperature zero.
- **Evals as tests.** A golden set of Danish and English article pairs scores clustering precision and
  recall separately, runs in pytest against recorded responses, and fails the build when it regresses.
  A cost ledger per edition sits beside it.
- **Cross-language contract discipline.** One JSON Schema owned by block 3, validated identically in
  Python and TypeScript, with a shared corpus of rejection documents both sides must refuse.
- **Idempotent checkpoints and receipts.** Import advances independently of publication; "already
  covered" memory advances only after block 3's activated receipt is acknowledged.

## Build order

Each package is one skill you can talk about, and each ends with a check you can show. Later packages
depend on earlier ones, so do them in sequence.

1. **Contracts and models.** Generate the edition models from block 3's schema. Validate all of block
   3's example documents and reject its rejection corpus. You learn: schema-driven types, the contract
   boundary.
2. **Bundle import.** Read a block 1 export, verify its hashes and counts, store articles and
   appearances in SQLite, make a repeated import a no-op. You learn: idempotency, migrations, the
   difference between a snapshot and a stream.
3. **Sections and the candidate window.** The feed-to-section table from the editorial policy file;
   the 72-hour window on publication time with newly observed items admitted. You learn: why
   provenance beats inference, the two clocks.
4. **Clustering and threads.** The single call, structured output, and the validator that splits
   implausible clusters back into singletons. Build the golden set here and keep it growing. You learn:
   structured outputs, prompt caching, evals.
5. **Scoring and selection.** The visible formula, section weights, `not_in_danish_media`, repeat
   suppression, diversity constraints, and a decision reason on every candidate. Pure code, fully
   unit-tested. You learn: how to keep judgment inspectable.
6. **Writing.** One call per selected story, producing the copy variants and callouts as contract
   models, followed by citation validation in code. The eight writing guidelines become the prompt and
   the reviewer's checklist. You learn: evidence packets, attribution by citation.
7. **Verification and preflight.** The bounded checking call with at most a small number of repairs,
   then block 3's `validate`. You learn: when a second model pass helps and when it is theatre.
8. **Publish, receipt, memory.** Call block 3, read the receipt, advance "already covered" from the web
   set, write the editorial log entry. You learn: activation as the only evidence of publication.
9. **The graph, cost, and scheduling.** Put the stages under LangGraph with a SQLite checkpointer,
   resume a killed run, record tokens and cost per edition, schedule one morning run in
   `Europe/Copenhagen`. You learn: durable workflows, observability.
10. **The operator's MCP server.** Health, dry runs, receipts, the editorial log, across all three
    blocks. You learn: MCP as an operations surface.

## Choices left open

- **Tracing.** Structured logs to stderr are enough for release 1. If you want a tracing product for
  the CV, Logfire pairs naturally with Pydantic; add it in package 9, not before.
- **Provider abstraction.** Start with one provider and one evaluated model behind a small interface.
  Adding a second provider is a package of its own if a measurement ever justifies it.
- **The editorial policy file's format.** YAML, read with `safe_load`, versioned in git, as block 1
  does for sources. The section table and the scoring publisher list live in it.
