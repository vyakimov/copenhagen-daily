# Golden example: Tuesday 15 September 2026, morning edition

This is the reference edition for block 2: the one the owner read and judged good. `spec.json` is the
desk's compact editorial decision, `edition.json` is the contract block 3 accepted and published from
it, `feeds.json` is the coverage inventory, and `../build_edition.py` turns the spec into the contract
by resolving every source from the block 1 bundle. A future block 2 should be able to produce an
edition of this quality from the same bundle, and its tests can use this contract as a fixture.

The bundle was a 72-hour publication window ending at 10:00 Copenhagen time, 1,903 articles from
131 feeds at sixteen publishers, all polled successfully.

## What the desk decided, and why

**Lead: the Russian frigate and the Danish helicopter.** Seven Danish outlets carried it within twelve
hours, it involves the Danish state directly, and it had a full arc by the cutoff: the incident, the
ministry's statement, the ambassador summoned, the prime minister's response. That is a lead on
breadth, recency, and section weight at once. The copy opens with the fact of record (what, where,
when, who responded), then the minister, then the prime minister's words in quotation, then two named
judgements: a maritime-law professor and Politiken's commentator. Nothing about Russia or NATO comes
from outside the sources. The quote callout is verbatim from DR's headline; the timeline's four rows
each trace to a source description.

**Secondaries.** Trump's energy-truce claim, because four Danish outlets carried it and the copy can
say plainly that neither country has confirmed it. The Supreme Court ruling, because five carried it
and it is a decision with a consequence. The AI share slide, because it is the day's development in a
thread the paper has run for three editions, with Trump's "sick conspiracy" as the new fact and Danish
sentiment as the local angle. Sweden's Centre Party refusing Kristersson, because it is a material
development in the election thread, not a rerun of Monday's lead. All four were written answer-first.

**Briefs.** Chosen for consequence and breadth, not volume: an inquiry's documents withheld, a
citizens' proposal crossing the Folketing threshold, a NATO shoot-down, an Emmys record, a ninth-grade
pass rate, murder charges. Culture and sport are represented lightly and only where a Danish outlet
made them news. Every lede is one sentence under 35 words and carries at least one number, name, or
decision.

**What was left out, and why.** Yesterday's diesel record and electricity price ran on the 14th and had
no new development beyond a party proposal, which became one brief. Novo's rebrand ran on the 14th;
its follow-ups were analysis of the same event, so only the new fact (a partnership ended) appears.
Mitch McConnell's return, Oasis skipping Denmark, a crane in Silkeborg, and Turkish social-media
closures were all carried by two or three outlets and were dropped for space, not eligibility.

**Sources.** Every article that supplied a fact or a quote used in the copy is a source. The lead had
more than sixteen candidate articles; live-blog entries and a rolling "latest on Ukraine" page were
left out in favour of dated articles, which is the inclusion rule the architecture now states. The
primary on each story is the scoring publisher's article that supplied the most of the copy. Seven
stories link international titles that covered the same event; none of them made a story eligible.

## What block 3 sent back, and how the desk answered

The device page holds three secondaries and four briefs. The first contract asked for four required
secondaries and six required briefs, and `publish` returned `composition_unavailable` listing the
stories that did not fit. The desk's repair was participation, not copy: the Sweden secondary gained a
brief fallback and became optional, and two briefs became optional. The next attempt failed on the
lead slot by 124 pixels, then, after a shorter deck and short headline, by 14. Because the bands size
to their content and the lead takes what remains, the last fix was to shorten three required briefs'
ledes by a line each. `fit` then passed and `publish` produced both outputs. That sequence,
participation first, then the lead's own variants, then the copy of the supporting stories, is the
repair order the architecture now records.

## What to notice about the voice

Compare "It is a thriller that may drag on" from the 14 September draft with "The overnight count left
two seats between the blocs". The second is the paper's voice: a fact, a number, no adjective. Where a
sentence rests on someone's judgement, that someone is named in the sentence: "Kristina Siig, professor
of maritime law at Aalborg University, tells Ritzau". Where it rests on the record, nobody is named and
the citation marker carries attribution. That distinction, more than any rule about length, is what
made this edition read as a newspaper rather than a summary.
