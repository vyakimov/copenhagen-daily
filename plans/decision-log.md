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
[design notes](design/README.md), and the
[roadmap](roadmap.md) of designed but unbuilt work.

---

## Structure and boundaries

**One repository, `copenhagen-daily`, holding all three blocks.** This is one product built by one
person on one schedule, so one repository is the right default. The three blocks occupy sibling
directories, `ingest/`, `editorial/`, and `publisher/`. Block 1's rule that no browser, model, or
credential enters the component touching untrusted feeds is a directory rule enforced by tests: nothing
under `ingest/` may depend on a browser, a model, or the Node toolchain. Coupling decides layout: blocks
2 and 3 share a contract that flows both ways and is still being designed, so they sit together and
change together; block 1 hands block 2 an immutable bundle over a schema that already shipped, so
`ingest/` changes rarely and independently.

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

**The schema is hand-written JSON Schema, not generated from Zod. Corrected 11 September 2026.**
Conditional quote attribution is expressible in JSON Schema; the earlier example claiming otherwise
was wrong. The reason for direct authoring is one explicit cross-language contract, with generated
TypeScript types, equivalent format assertions, and a shared acceptance/rejection corpus. Cross-ID
integrity still needs semantic checks and block 3's final `validate` preflight. Published schemas are
immutable numbered artifacts: accepted-shape changes, including optional additions, create the next
integer version. Rejecting unknown fields means an older reader is not forward-compatible with new
producer vocabulary. Both blocks select an explicitly supported schema version and digest.

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

**One title.** The first release is one newspaper with one policy, one schedule, one masthead, one
archive, and one device pointer. The store and release carry no title prefix. Multiple titles are designed
in the [roadmap](roadmap.md).

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

**Overflow detection and magnitude have different authority. Revised 11 September 2026; harness
verification pending WP 0.** Check both scroll axes, nested constrained regions, and page bounds.
Multi-column overflow can create extra columns sideways; fragmentation can leave unused space that
a single-column probe cannot account for. Actual clipping always rejects a candidate even when the
probe reports slack. That disagreement is an unreliable estimate, not an internal error. Line and
character advice is nullable; the final capture context repeats checks. Retain the experiments as
regression fixtures instead of treating browser assumptions as measured facts.

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

**Publication has durable state even without a database. Settled 11 September 2026.** Immutable
storage, live activation, and command acknowledgment are distinct events. Prepare and verify a full
release, record durable intent, promote immutable objects, then swap `live` and retain an activation
record. Each release owns its index snapshot. Recovery completes a pending transition without
rerendering; receipt lookup reconciles lost stdout. Hash stored receipts in manifests and return the
manifest digest outside the stored receipt to avoid circular hashing. Post-commit cleanup is best
effort. See the implementation plan's protocol and its three crash boundaries.

**Release-1 tests guard invariants and contracts, nothing else. Settled 11 September 2026.** The first
handoff draft asked for crash injection at every transition, fuzzing of every string field, concurrent
build isolation, a Python validator inside the Node package, and pixel-tolerance visual regression. That
is more verification than block 1 needed, and each item guards a hypothetical rather than an invariant.
The rule now: a test that holds no Section 1 invariant and no published contract is not written. Crash
injection is three boundaries the protocol reduces every interruption to; escaping is one fixed
injection string; visual regression is a manual re-inspection of checked-in reference PNGs before a
renderer change; the Python validator is block 2's test when block 2 exists.

**Type is Newsreader and Libre Franklin. Settled 11 September 2026 by specimen.** The dense fixture
was set five ways and compared in the browser: the original Playfair Display with Source Serif 4,
Newsreader with Libre Franklin, Libre Caslon with Libre Franklin, Newsreader headlines over Source
Serif, and Newsreader with a Chomsky blackletter nameplate. Playfair was dropped because its Didone
hairlines break first at 16 grey levels and because it has become the default face of generated
broadsheets. Caslon Display comes in one light weight, elegant on screen and too thin for the panel.
The nameplate was memorable but unproven on the device. Newsreader was chosen for its optical-size
axis, which gives headline and text cuts from one family, and Libre Franklin because a plain
grotesque for labels is the second voice the reference has and the page lacked.

**Danish media decide what is news; international media are linked, never scored. Settled 14 September
2026.** The paper is an overview of what Danish outlets report. A story carried by the FT, the NYT, and
any number of foreign outlets but by no Danish one is not news for this title and is dropped at selection
as `not_in_danish_media`. A story carried by DR and Berlingske that the FT also covers keeps the FT article
as a source and a link. Breadth and prominence count only the scoring publishers, listed in the editorial
policy file, so that adding an international feed can never change what gets selected. The list is every
Danish outlet block 1 collects, nine since 14 September 2026, so adding a Danish outlet to the collector
widens what counts as news. The price is that only Børsen's and Jyllands-Posten's ranked surfaces still
score prominence; that term was already the weakest.

**Copy is facts first, and colour needs a name on it. Settled 14 September 2026.** Three evaluation
editions read as padded and editorialised because the writer paraphrased RSS teasers faithfully, so
DR's "valggyser" and Altinget's sketch-writing surfaced as the paper's own voice. The writing
guidelines in the [editorial architecture](news-editorial-architecture-plan.md) now require a new fact
per sentence, attribute any colour to the outlet or speaker in the sentence itself, synthesise across
sources instead of a paragraph per outlet, put the answer first, and set a word budget per role. They
are guidelines rather than validators: attributed colour is acceptable on a slow day, unattributed
colour never is. A source is named in the sentence only when the sentence rests on that source's
judgement, observation, or access; a fact of record is cited by the marker alone, so naming an outlet
in prose reads as "one outlet's view" and is never used for settled facts. Above all the paper respects
the reader's time: it never pads for its own sake, a slow
day makes a shorter paper rather than a thinner one, and the reader is meant to finish and move on.

**The web edition is a grid with the sheet kept as a one-word switch. Settled 14 September 2026.**
Three layouts were compared on three fresh editions: the lead beside a rail with flowing columns below,
and one sheet of newspaper columns with a spanning lead headline, ragged and justified. The sheet fills the
page on every kind of day; the grid gives the front page a clear opening and was preferred on balance.
Both are kept because the cost is one small placement block each, on one shared story renderer and one
type scale; if the sheet goes unused it is deleted, never left to drift. Justification won over ragged
right once the inline citation markers were
removed, which had been the real cause of the rivers. Hyphenation moved from the browser to the build:
soft hyphens from TeX patterns make every browser break identically and make the exception list ours.
Knuth–Plass was rejected for the web because it needs a script or a fixed line width; it remains an
option for the fixed-width device page.

**Attribution is a trailing citation, not a sentence prefix. Settled 11 September 2026.** The first
fixtures opened every paragraph with "X reports that", and rendered pages read as a machine
repeating itself. Rotating the phrasing was rejected because rotated synonyms on every sentence read
as generated faster than plain repetition does; dropping attribution was rejected because the
evidence discipline depends on it. Paragraphs and ledes became `{text, sources[]}` in the edition
contract, with publisher ids validated against the story's sources and rendered as a small-caps
marker after the text. Prose names a publisher only when publishers disagree.

**The ingestion code moved into `ingest/` on 11 September 2026.** Done with `git mv`, runtime state and
the virtual environment moved alongside, and verified by the collector's own offline check and smoke
actions from outside the repository. No scheduler entry referenced the old path.

**Object storage is a future delivery design, not the local commit protocol. Clarified 11 September
2026.** Immutable prefixes and a single release pointer could replace filesystem primitives. Atomic
single-object writes do not make multiple root/index updates transactional. Hosting remains deferred;
any adapter must define coherent activation and recovery before it is implemented.

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
which fit and never composes wording. Release 1 tries the first candidate or none, drops callouts
before stories, and does not restore them after repairs. The full web edition carries all approved
callouts regardless of device placement.

**One device participation field. Settled 11 September 2026.** `required`, `optional`, and `reserve`
are mutually exclusive. Ordered omission/reserve lists must equal those sets. Every story, including
device reserves, is already accepted for the web. Story-array order is authoritative. Sparse layouts
permit empty supporting bands, and count-level repairs precede measurement. The fit policy is bounded
and greedy; a failure does not prove no permissible arrangement exists.

---

## Editorial signals

**Sections come from feed provenance, never from a model. Measured.** Every appearance names the feed it
was seen in and whether that feed is a section, homepage, or latest feed. Filtering to section feeds gives
the publisher's own placement decision. Coverage is 95 to 99 per cent for four of six publishers, and was
zero for NYT and Politiken until section feeds were added to the configuration on 9 September 2026.

**Keep the set of sections, not a single label. Measured.** Roughly an eighth of articles appear in more
than one section feed, and the overlaps are meaningful rather than noise. Forcing one label discards real
editorial signal.

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

**Edition revisions and correction notices.** Designed in the [roadmap](roadmap.md). The first release
publishes each edition id once and corrects mistakes in the next edition. Gate: a real correction is
needed on a published edition and the next-edition workaround proves inadequate.

**Multi-page device output.** Designed in the [roadmap](roadmap.md). The first release renders exactly one
device page, so there is no page budget, no inside-page composition, and no playlist coordination. Gate:
a week of material optional omissions or repeated required-story device fit failures. Required
stories cannot be silently omitted from a successful device edition.

**Multiple titles.** Designed in the [roadmap](roadmap.md). Gate: a second remit is actually wanted, such as
a sports-and-culture paper beside the news paper.

**Visual prominence capture.** Designed in the [roadmap](roadmap.md). Gate: a recurring, named
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
