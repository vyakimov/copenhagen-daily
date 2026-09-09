# Decision log

Every choice in this project that required judgment, with the reasoning that produced it and the
evidence where evidence exists. Recorded 8 and 9 September 2026.

The architecture plans say what the system does. This says why, and what was tried and rejected on the
way. Entries marked **Reversed** are the most useful ones: they record a position that was held and
abandoned, so nobody re-derives it. Entries marked **Measured** rest on a test that was actually run,
not on reasoning alone, and the test is named so it can be repeated.

Companions: [Block 1 implementation](news-ingestion-implementation-plan.md),
[Block 2 editorial architecture](news-editorial-architecture-plan.md),
[Block 3 publishing architecture](news-publishing-architecture-plan.md),
[Block 3 implementation](news-publishing-implementation-plan.md),
[design notes](design/README.md), and
[deferred visual prominence capture](deferred-visual-prominence-capture.md).

---

## Structure and boundaries

**Two repositories, not one and not three.** `news-gatherer` holds block 1. A downstream
`personal-newspaper` holds blocks 2 and 3. The reason is that coupling is asymmetric: block 1 hands
block 2 an immutable bundle over a schema that already shipped and works, one-directional and stable,
while blocks 2 and 3 share a contract that is still being designed and flows both ways. Splitting the
pair that changes together while joining the pair that does not would be exactly backwards, which is
what rules out three repositories. A single repository would be the better default if nothing were built
yet, since this is one product built by one person on one schedule; block 1 stays separate because it
already exists, works, and carries a real rule that no browser, model, or credential enters the component
touching untrusted feeds.

**Repository layout does not affect the architecture.** All three blocks communicate through a shell
wrapper, a JSON envelope on stdout, and files on disk. Nothing imports across a block boundary at
runtime. The repository question only decides where a change lands and what one test run can check.

**Contract drift is handled by fixtures, not by topology.** Each side keeps a frozen artifact of its
neighbour in its test suite, so a break surfaces as a failing test at the boundary. This works under any
repository arrangement, which is why it beats reorganising.

**Block 3 owns the edition schema. Reversed.** The initial position was that the producer should own the
contract, on the grounds that the reader should not define what the writer must produce. That was wrong.
Block 3 is not merely the reader, it is the renderer, and what a renderer can draw is a hard constraint
rather than a preference. You cannot add a callout kind by editing block 2, because nothing would exist
to draw it. A browser owns the HTML element set and pages are written against it. The real concern
underneath was mechanical, not about ownership, and is recorded in the next entry.

**The schema is hand-written JSON Schema, not generated from Zod.** Zod expresses constraints JSON Schema
cannot carry, such as a refinement requiring a quote callout to name a speaker. Translating drops or
weakens those, so block 2 would validate against a weaker artifact than block 3 enforces, pass, write the
file, and be rejected at the publishing end for a mistake made at the editorial end. Both sides read the
same file. TypeScript types are generated from the schema rather than the reverse. Because block 3 owns
the vocabulary it can break block 2 unilaterally, so the schema evolves additively within a major version
and breaking changes bump it.

---

## The product

**One edition serves every reader. Reversed.** An earlier answer assumed per-reader personalisation and
warned that language model cost would dominate and scale with the user count. That assumption was wrong.
With one shared edition, every cost except bandwidth is fixed, and fixed costs do not care how many
readers there are.

**Identical content for all readers is the best possible property for cheap hosting.** A CDN caches each
edition once per edge and serves the rest from there, so the origin sees a handful of fetches per edition
regardless of audience size. This is why news sites are cheap to run and personalised feeds are not.

**Block 2 is an editorial desk, not a recommender.** What the paper covers is a standing decision the
owner writes down, the way a masthead decides its remit. No reader profile, no reading history, no
behavioural signal. This keeps the system free of personal data, keeps every reader on the same public
page, and makes an edition's cost independent of readership.

**Reader tracking is forbidden rather than merely absent.** No click logging, dwell time, or per-reader
analytics. Those would recreate the personal data the design exists without, and they answer a question
the paper is not asking.

**Multiple titles are the supported way to serve different appetites.** A news title and a
sports-and-culture title are two policies, schedules, mastheads, and archives, each publishing one public
edition. They share collection, clustering, and matching; each title's policy selects from the shared
candidate set; the selections are unioned and each distinct story is written once.

**Selection happens before writing, not after. Reversed.** A first pass had the shared story pool written
first and each title selecting from it. That pays to write stories nobody runs. Selecting per title first,
unioning, then writing each distinct story once is cheaper and preserves the same sharing benefit.

---

## Publishing and layout

**The web edition is the first-class product; the device PNG is a separate reduced artifact.** They share
an edition, a design language, and a component vocabulary, but not a layout, a page budget, or a build
path. Nothing in the web edition is constrained to keep parity with the panel. A device fit failure
publishes the web edition anyway and leaves the device pointer on the last good page, so the panel keeps
a readable page rather than a gap. The reverse is not allowed.

**Editions must differ from day to day, and the variation comes from editorial signals.** Exactly one lead
story, with the number of secondary and brief stories, the composition, and the callouts varying with the
contract from block 2. Type sizes, margins, rule weights, and the palette never vary. The publisher adds
no randomness to appear hand-made.

**Astro renders the web edition only; the device page uses plain TypeScript templates.** Astro's Container
API is still exported as experimental, is documented as subject to breaking change even in patch releases,
already moved an entry point within the Astro 7 cycle, is scoped by its own docs to component testing, and
is silent on whether component styles survive rendering. More decisively, `.astro` is not a Node-loadable
format, so any Container design drags a build system into the command-line tool. Measuring a dev-server
route was also rejected because dev mode injects a client script into the page, violating the rule that
the device page ships no JavaScript. Astro's value is routing, archives, and permalinks, none of which a
fixed-size page with no links needs.

**Astro is version 7, not 5. Measured.** Checked 8 September 2026. Astro 6 shipped March 2026 and moved to
Zod 4; Astro 7 shipped June 2026 and changed the `compressHTML` default to a mode that strips newlines
between inline elements, which would silently eat the spaces in source rows. The config sets it
explicitly.

**Overflow detection differs by slot kind. Reversed and measured.** An earlier draft recommended comparing
the last child's bottom edge to the container's content box. That is the least reliable of the options: it
misses content overflowing past the last child, is fooled by collapsed margins, and in multi-column layout
the last child sits inside the box. Block-flow slots compare scroll height to client height. Multi-column
slots must compare scroll *width*, because a constrained height pushes overflow into extra columns
sideways while the heights stay equal. Magnitude comes from an off-screen single-column clone probe.

**`-strip` is required and `+dither` is a no-op. Measured.** Verified 8 September 2026 with ImageMagick
7.1.2-31 against a rendered composition. The conversion yields exactly 16 grey levels at 4-bit depth.
Two runs with `-strip` hash identically and two without it do not, because of the embedded timestamp
chunk. `-depth 4` rounds per pixel rather than quantising, so an explicit `+dither` changes nothing;
it is asserted in a test rather than added as decoration, so that introducing `-colors 16` later forces
the conversation.

**Archived editions are never rebuilt.** Each is published once into its own immutable directory; only a
small mutable shell is regenerated. Rebuilding everything would replace archived files whenever the layout
changed or a dependency was upgraded, invalidating every hash recorded in every old manifest. That is the
reason, not build time.

**Object storage simplifies the publication design rather than complicating it.** The staging-directory
rename, hardlinked release trees, and symlink docroot exist to make a filesystem behave the way object
storage already does. On S3 or Blob Storage there are no hardlinks, symlinks, or atomic directory renames,
so instead write each edition under its own immutable prefix, then overwrite the root index objects last.
Single-object writes are atomic, so the index never points at absent content.

---

## Design

**Playfair Display and Source Serif 4. Reversed.** The first attempt used Bodoni Moda for display type.
Rendering at device size showed its hairline strokes thinning to near-invisibility and its optical-size
axis fighting the fixed sizes. Playfair holds up at 16 grey levels, which is what the panel provides.

**Device greys sit exactly on palette levels.** Every device colour is of the form `#XYXYXY` with equal
digits, so it is a multiple of 0x11 and lands on a 16-level step. Only anti-aliased glyph edges move
during quantisation, so text stays crisp and dithering is never needed for text.

**Five callout kinds, each owned by a story.** Quote, figure, facts, box, and timeline. A callout's text
is approved copy written in block 2 with the same evidence discipline as the body; block 3 chooses only
which fit and never composes wording. Callouts are the first thing dropped when a page overflows and the
last thing added, so a busy day loses emphasis before it loses stories.

---

## Editorial signals

**Sections come from feed provenance, never from a model. Measured.** Every appearance names the feed it
was seen in and whether that feed is a section, homepage, or latest feed. Filtering to section feeds gives
the publisher's own placement decision. Coverage is 95 to 99 per cent for four of six publishers, and was
zero for NYT and Politiken until section feeds were added to the configuration on 9 September 2026.

**Keep the set of sections, not a single label. Measured.** Roughly an eighth of articles appear in more
than one section feed, and the overlaps are meaningful rather than noise. Forcing one label discards real
editorial signal, and a story can legitimately be eligible for two titles.

**Resolve sections at edition time from accumulated appearances.** An article often reaches a section feed
on a later poll than the latest feed that first surfaced it, so a section assignment frozen at first sight
is frequently wrong.

**Opinion is a flag, not a section.** An opinion piece about culture is both. A comment column should
compete for a culture slot carrying a marker rather than occupy a separate section that displaces its
subject.

**Two Børsen feeds map to no section on purpose.** `borsen.breaking` and `borsen.longread` describe
urgency and format rather than subject, and their articles reliably appear in a subject feed as well.

---

## Ranking

**The formula is a small visible calculation, not a model call.**

```
base  = 0.45·breadth + 0.10·peak_prominence + 0.30·recency + 0.15·thread_strength
score = base × section_weight
```

**Section weight multiplies rather than adds, which is what makes the numbers mean something.** The ratio
between two section weights is exactly the margin a story needs to overcome them. With Denmark at 1.0 and
technology at 0.5, a technology story must reach twice the base score of the best Danish story to lead.
An editor can reason about that directly instead of guessing at constants.

**Breadth carries the most weight because prominence is measurably weak. Measured.** Position one in
almost every section feed scores identically, because the score is a within-publisher feed position and
section feeds are short. Ranking on prominence alone put a single-publisher local item above a story that
five of six publishers were running. Cross-publisher breadth is what separates the day's big story from a
well-placed minor one.

**Prominence counts only feeds whose order is editorial. Measured.** Feed ordering was tested on
8 September 2026. The three homepage feeds are ranked, as are `nytimes.world` and `borsen.finans`. Every
`latest` feed and most section feeds, including `dr.indland`, `politiken.indland`, `ft.world`, and
`berlingske.samfund`, are in strict reverse-publication order, so position carries no editorial signal.
Scoring those counted recency twice under another name.

**Unknown prominence is recorded as unknown, not as low.** A story missing from the NYT homepage feed was
genuinely not front-paged, which is real negative evidence. A story missing from a DR ranked surface tells
us nothing, because DR publishes none. Treating those as the same number was the flaw that made prominence
untrustworthy.

**Recency is measured in editions, not hours. Reversed.** A linear decay over 48 hours was tried and
discarded because it barely separated this morning from yesterday afternoon, which is the distinction a
daily paper cares about most. Anchoring to the previous edition's cutoff also handles the awkward case
correctly: a story filed just after yesterday's deadline is new to this edition even though it is over a
day old.

**Candidacy and recency use different clocks.** Candidacy is gated on observation time so a late discovery
stays eligible; recency is scored on publication time so a genuinely old story is penalised for being old.
A three-day-old article nobody noticed can earn a brief but should not lead. Collapsing these into one
clock forces a choice between missing late arrivals and resurfacing stale news.

**The 72 hour window is a backstop, not the main mechanism.** With recency anchored to cutoffs, anything
past two editions already scores 0.15 and is buried. The gate exists to stop genuinely stale material
appearing at all. One exemption: a material correction to an older article is new information and is
admitted regardless of the original's age.

**Repeat suppression, not recency, is what stops yesterday's lead reappearing.** A published story does
not return unless its thread produces a material development, which arrives as a new cluster with its own
age. The recency term only ever ranks stories not yet run, which is why a moderate coefficient suffices.

---

## Clustering and threads

**One model call per edition clusters the whole candidate window. No retrieval stage.** Measured: a title
plus description averages 51 tokens, so a few hundred candidates is 15,000 to 30,000 input tokens, which
is negligible against the cost of writing the stories. The stronger argument is what it deletes. The
two-stage retrieval design required an embedding model, a similarity threshold, a candidate-pair
generator, and a cache to keep coherent with all three, and it was fragile precisely where the work is
hardest. Cross-lingual Danish and English matching is where embedding thresholds hurt most and where a
capable general model needs no configuration.

**Return groups, not per-article assignments.** Clusters carry an event description, member identifiers,
and a confidence; anything unmentioned is a singleton. Most articles are singletons, so output stays
short, and long enumerations are where a model drifts or silently drops an identifier. The event
description is what makes a cluster checkable afterwards.

**The cheap signal moved from before the model to after it.** The lexical and temporal checks that would
have proposed candidates now validate the model's output. Same code, better position: a pre-filter's
misses are invisible and permanent, while a validator's flags are visible and free to review.

**Cross-publisher merges get the strictest scrutiny.** Breadth carries the most ranking weight, so an
over-merge does not merely duplicate a story, it promotes one that was never that big. Cluster errors are
amplified exactly where the stakes are highest.

**Naive transitive clustering over-merges. Measured.** A clusterer that merged any two articles sharing
rare terms and closed transitively produced clusters spanning business, Denmark, world, climate, and
culture simultaneously. This is empirical confirmation of the standing rule against blind connected
components, and it is the failure mode the validator exists to catch.

**Thread attachment is deliberately looser than cluster merging.** A bad merge changes what gets
published, because two events become one story and one disappears. A bad thread attachment changes a
ranking nudge and a link. The conservative bias belongs on clustering and must not be copied onto
threading, which is what makes threading cheap to get right.

**Thread strength lifts a story only if this title already published from that thread.** The value being
captured is continuity for a reader who read the earlier edition, not a generic boost for busy topics.
The term is worth 0.15 and decays by editions since the paper last ran the thread; setting it to zero
reproduces the behaviour of a paper with no memory. The failure mode to watch is a long-running story
that never dies and crowds out fresh news.

---

## Deferred, with gates

**Visual prominence capture.** Recorded separately in
[deferred visual prominence capture](deferred-visual-prominence-capture.md). Gate: a recurring, named
complaint in the editorial log that single-publisher scoops are being buried, across several weeks of real
editions.

**Homepage markup extraction.** Assessed 9 September 2026 and not worth a subsystem. Politiken exposes
usable attributes, Berlingske hides its content in an opaque data blob, and DR uses hashed class names
that would break silently on every redeploy.

**Publisher photography.** 24 of 26 sampled articles carried an image URL, so the raw material exists. A
URL in a feed does not establish a reuse licence, so this stays closed.

**A content management system, Paged.js, PDF output, and a portrait device profile.** None are needed for
a first release and each is available later without rework.

---

## Open questions

**Publisher licensing is the largest unresolved risk, and it is not technical.** A personal digest for one
reader is a very different position from a public page redistributing summaries of Financial Times, New
York Times, Politiken, Børsen, Berlingske, and DR reporting. Charging for it would be a further
escalation. This deserves an answer before the site is promoted.

**Whether multi-column overflow really surfaces through scroll width.** It is what the specification
requires and what browsers are believed to do, but it was not run. It decides the measurement path for one
of the three device compositions and should be spiked first.

**Whether the world section weight of 0.7 is right.** A five-publisher global catastrophe beats a strong
domestic story by three per cent under the current weights. That was accepted deliberately for a
Denmark-focused brief, but it is the number to revisit first if editions read wrongly.

**Whether block 1's manifest gap matters in practice.** It writes empty coverage gaps and warnings and
omits the configured feed inventory its own plan requires, so block 2 must treat coverage as unknown
rather than complete until it is fixed.
