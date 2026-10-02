# Editorial writer split: five review findings

Date: 2 October 2026

Scope: the uncommitted changes introducing separate desk and per-story writer sessions,
compressed reading views, and related runner changes. Line references describe the working tree
at review time. This report records findings; no implementation fixes were made during review.

## 1. The writer's evidence isolation is not enforced

Location: [`editorial/src/news_editorial/run.py`, line 178](../../editorial/src/news_editorial/run.py#L178).

Each writer receives a focused brief, but it also gets the `Read` tool, the whole repository through
`--add-dir`, and the run directory as its working directory. That leaves `window.json`, other
stories' briefs, and other run artifacts accessible.

This is a substantial improvement over automatically putting the whole window into every writer's
context. However, the documentation's claim that a writer “sees that story's evidence and nothing
else,” and the decision log's corresponding guarantee, are stronger than the implementation
supports. The finding concerns available access; the review did not demonstrate a live writer
reading another story's evidence.

**Suggested fix:** supply the brief, style rules, and example directly to a tool-free writer, or
enforce a read boundary around an isolated directory containing only those inputs. Until then,
describe this as context separation rather than guaranteed evidence isolation.

## 2. A writer retry can silently replace the evidence-integrity baseline

Location: [`editorial/src/news_editorial/run.py`, line 681](../../editorial/src/news_editorial/run.py#L681).

When a writer returns unusable JSON, the runner creates `brief-retry.json` and calls
`_record_inputs()`. That rehashes all protected inputs while the writer phase is still running.
Any input changed since the original baseline can thereby become the newly accepted baseline.

**Reproduced:** a fake writer changed `window.md`, returned invalid JSON, and then returned valid
copy on retry. The run finished as `published`, without an `input_modified` failure. This used the
existing test fixtures and fake publisher; it did not publish a live edition.

The real writer's read-only tool configuration reduces the opportunity for this, but the integrity
guard itself is bypassed by this sequence. Concurrent writers also make broad baseline replacement
particularly undesirable.

**Suggested fix:** preserve existing recorded hashes and add only the new runner-created retry
brief's hash. Verify existing inputs before any intentional baseline update.

## 3. Headline equality is treated as text equality, hiding distinct evidence

Location: [`editorial/src/news_editorial/window.py`, line 124](../../editorial/src/news_editorial/window.py#L124).

`_text_keys()` makes a normalized title sufficient for deduplication. `_listing()` then suppresses
the later article's title and description and tells the desk it is the “same text” and belongs with
the first article.

Identical headlines can accompany different descriptions, updates, or recurring liveblogs. This
changes the desk's evidence, rather than merely compressing repeated text.

**Observed in the rerun data:** 151 suppressed entries had differing normalized descriptions on
1 October, and 176 on 2 October. These are not necessarily distinct events, but they are not
identical text. Examples include recurring politics liveblog headlines.

**Suggested fix:** reserve “same text” suppression for matching substantive text. For matching
titles with different descriptions, retain the distinct description and label the relationship
accurately. Prefer the richer representative when one version has no description.

## 4. Queued writers and retries can exceed the overall run deadline

Location: [`editorial/src/news_editorial/run.py`, line 714](../../editorial/src/news_editorial/run.py#L714).

The runner calculates one timeout before submitting every story to the thread pool. Each queued
job receives that same timeout when it eventually starts; second attempts also reuse it.

For example, if five minutes remain, several successive batches can each start with a five-minute
allowance. The executor waits for submitted jobs to finish, including after a failure. Consequently,
the configured overall wall-clock limit does not bound this phase. This finding follows from code
inspection; the review did not run a live edition to deadline exhaustion.

**Suggested fix:** calculate the remaining budget immediately before every writer invocation,
including retries. Stop starting queued work once the deadline passes, and ensure active
subprocesses cannot outlive the overall deadline.

## 5. A partially written cached story prevents automatic recovery

Location: [`editorial/src/news_editorial/run.py`, line 802](../../editorial/src/news_editorial/run.py#L802).

Resume logic considers a story reusable whenever `story.json` exists. It does not parse or validate
it first. Meanwhile, story files are written directly rather than through an atomic rename.

**Reproduced:** a cached story containing only `{` caused an `internal_error` with `JSONDecodeError`.
It was skipped by the writer and failed during assembly. Subsequent retries encounter the same
file. The reproduction used the existing test fixtures.

**Suggested fix:** write story files atomically and validate cached copy before reusing it. Set
malformed or invalid files aside and regenerate only the affected stories. Ideally, also bind
cached copy to the brief and selection that produced it.
