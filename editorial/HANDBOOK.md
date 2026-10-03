# The desk handbook

How an edition of Copenhagen Daily is made, written for the editor, whether that editor is a person
running the desk by hand or the model inside block 2. The [architecture](../docs/editorial-architecture.md)
says what the paper is and why; the [policy file](policy.yaml) holds the numbers; this page is the
working method. The [golden example](examples/2026-09-15-morning/NOTES.md) shows the result.

The editor is trusted. These pages give broad guidance and a few hard rules; where they are silent,
use judgement and be ready to explain it in the editorial log. Do not look for a rule for everything,
because there deliberately is not one.

## The run

1. **Collect and export.** Poll block 1, then export a 72-hour publication window ending at the
   cutoff. Confirm every feed polled; if some failed, the edition says so in its coverage note.
2. **Read the last fortnight of editions.** Load the published contracts from block 3's store, newest
   first. Note every story id, the articles it carried, its thread, and the day it ran. A candidate that
   overlaps a published story's articles is covered unless it brings a material development: a new
   decision, number, actor, or consequence. "More analysis of the same event" is not a development.
3. **Read the window.** The Danish publishers: articles from the last 24 hours with their descriptions,
   the rest by headline. The international titles are a separate list, read by a subagent only to
   attach them to the events already found.
4. **Cluster by event**, conservatively. One event, one story. A thread is looser: several events, one
   running narrative. When in doubt, split. Then attach the international titles.
5. **Select.** Eligibility needs at least one scoring publisher. Rank by breadth among scoring
   publishers, recency measured in editions, the section weight, and thread continuity. Then apply the
   budget below and the diversity rule: no publisher dominates, no section takes more than half the
   page, culture and sport appear only when a Danish outlet made them news.
6. **Log** what was selected and rejected with a reason, and anything that felt wrong. The desk's work
   ends here.
7. **Write**, one story at a time, each from its own evidence alone, to the guidelines in the
   architecture plan; then check every sentence against its sources.
8. **Build, validate, publish.** Never change the edition id between attempts before publication.

## The budget

The paper is the web edition, and it carries everything accepted. A kitchen screen shows the lead and
as many of the next stories as fit, decided mechanically by block 3 from the same copy, so nothing is
marked for a device by hand and no story needs a shorter form to make room.

| Role | Web |
|---|---|
| Lead | exactly 1, first |
| Secondary | as many as the day earns, typically 3 to 5 |
| Brief | as many as earn a line, typically 8 to 16 |

A quiet day is a shorter paper: two secondaries and five briefs is a complete edition.

## Sources and the primary

A story's sources are every article that supplied a fact, a quotation, or a judgement used in the
copy, from scoring, linked, and corroborating publishers alike. A press release from Via Ritzau is
evidence for a story a scoring publisher reports, never a story on its own. Include at most one article per publisher unless a
second carries distinct evidence the copy uses. Prefer dated articles to live blogs, rolling pages,
and video reels; include those only when they are the sole coverage. The contract caps sources at
sixteen, which is ample under this rule; a story that genuinely exceeds it is the moment to raise the
cap with a schema version, not to drop evidence.

The primary is the scoring publisher's article that supplied the most of the copy. On a tie, the one
with the fuller description; on a further tie, the earlier one. The headline links to it.

Wire copy is an outlet's article like any other for these rules, the primary included. An article
flagged `wire:<agency>` in the window is the agency's piece on that outlet's page: list it as a source
by its number, and `build` marks it, so the page credits the agency under the story while the headline
still links to the outlet that carries it. The style guide says whom the prose names.

## Callouts

Use at most one callout on a secondary and up to three on a lead. General guidance, not an
algorithm:

- A **figure** beats a quote when one number is the story and the copy would otherwise repeat it.
- A **quote** earns its space only when the words themselves carry the news, are verbatim in a
  source, and have a named speaker. A paraphrase is never a quote.
- A **timeline** earns its space when the order of events is the point and each row traces to a
  source; three or four dated rows, never a list of everything that happened.
- **Facts** are for two to four short items a reader would otherwise have to assemble from the body.
- A **box** sets apart one phrase that is itself news: a decision, a demand, a deadline.

## Kickers

A kicker names the section a reader files the story under, in the paper's vocabulary from the policy
file. It may be more specific than the mapped section when that helps the reader ("Defence" rather
than "Denmark", "Prices" rather than "Economy"); it may not invent a section the policy lacks. Opinion
is a secondary kicker, never a section.

## Checking the copy

A separate checker reads `check-input.json`, nothing else: each story's sentences and that story's
own evidence rows, not the spec, not the notes, not the editor's reasoning. It reads every sentence, the headline and callouts included, against the
sources the sentence cites, and marks each one supported, with the passage, or unsupported, with the
reason: no source says it, the attribution changed, a paraphrase became a quotation, a quotation has
no speaker, the sources disagree and the copy does not. The checker marks; it never rewrites. A check
can catch a mistake; it is not proof of truth.

The repair is a strike, not a rewrite. Unsupported sentences are struck by the desk tool, and nothing
new enters. A story still stands if its opening sentence survived and at least two thirds of its words
remain. A story that stands ships as struck. A story that does not stand is written once more, in its
own session, with the strikes and their reasons in the brief, and the rewrite is checked once more. A story that fails
again falls to its headline and a link to the primary. The failure mode is a shorter story, never an
invented one, and a missing paragraph is preferable to a confident invention.

## Limits

The policy file's `limits` are the desk's deadline discipline. At most that many stories are written;
the rest of the ranking is recorded as `outside_budget`. A checked story goes back at most once. When the editor or the checker runs past its wall clock, the run stops, the last
published edition stays with its own date, and the log says why. A limit hit is a shorter paper or no
paper, never a padded or a late one.

## Before publishing

- Exactly one lead, first.
- Every quotation is verbatim in a source and has a speaker.
- Every sentence that rests on a judgement names its source in the sentence; every fact of record
  cites by marker only.
- No fact, background, or explanation from outside the sources, except the explanation of a name or
  term on first mention, declared with the copy and verified against Wikipedia (the style guide's
  clarity rule).
- No name, place, institution or term left unexplained that a reader outside Denmark could not place.
- Word budgets respected as ceilings: lead 120 to 180, secondary 60 to 110, brief under 35.
- The coverage note says what was read and what failed.
- The edition id has not been published before.

The [style guide](STYLE.md) settles spelling, numbers, time, names, institutions, and quotation
marks; where it is silent, follow the golden example.
