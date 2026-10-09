# Decision log

Every choice in this project that required judgment, with the reasoning that produced it and the
evidence where evidence exists.

The architecture plans say what the system does. This says why, including the alternatives that were
weighed and why they lost, so nobody re-derives them. Entries marked **Measured** rest on a test that
was actually run, not on reasoning alone, and the test is named so it can be repeated.

Companions: [Block 1 architecture](ingest-architecture.md),
[Block 1 implementation](ingest-architecture.md),
[Block 2 editorial architecture](editorial-architecture.md),
[Block 3 publishing architecture](publisher-architecture.md),
[Block 3 implementation](publisher-architecture.md),
[design notes](design/README.md), and the
[roadmap](roadmap.md) of designed but unbuilt work.

---

## Structure and boundaries

**One repository, `copenhagen-daily`, holding all three blocks.** This is one product built by one
person on one schedule, so one repository is the right default. The three blocks occupy sibling
directories, `ingest/`, `editorial/`, and `publisher/`. Block 1's rule that no browser, model, or
credential enters the component touching untrusted feeds is a directory rule, stated in `AGENTS.md` and
kept by review rather than by a test: nothing under `ingest/` may depend on a browser, a model, a
credential, or the Node toolchain. Coupling decides layout: blocks
2 and 3 share a contract that flows both ways and is still being designed, so they sit together and
change together; block 1 hands block 2 an immutable bundle over a schema that already shipped, so
`ingest/` changes rarely and independently.

**Repository layout does not affect the architecture.** All three blocks communicate through a shell
wrapper, a JSON envelope on stdout, and files on disk. Nothing imports across a block boundary at
runtime. The repository question only decides where a change lands and what one test run can check.

**Contract drift is handled by fixtures, not by topology.** Each side keeps a frozen artifact of its
neighbour in its test suite, so a break surfaces as a failing test at the boundary. This works under any
repository arrangement, which is why it beats reorganising.

**The plans directory is retired; `docs/` holds the cross-block documents and each block describes
itself. Settled 30 September 2026.** The three implementation plans were removed once the code they
planned existed, because a plan that has been built is either a duplicate of the code or a lie about
it. What survives in `docs/` is the three architecture documents, this log, the roadmap, the AWS
delivery page, the design notes, and the reviews. The as-built description of each block is its own
`README.md` and `OPERATIONS.md` (block 1's operations live in its README), next to the code that they
describe, so a change to behaviour and a change to its description land in one commit.

**Block 3 owns the edition schema.** The producer-owns-the-contract instinct, that the reader should not
define what the writer must produce, does not apply here. Block 3 is not merely the reader, it is the renderer, and what a renderer can draw is a hard constraint
rather than a preference. You cannot add a callout kind by editing block 2, because nothing would exist
to draw it. A browser owns the HTML element set and pages are written against it. The real concern
underneath is mechanical, not about ownership, and is the next entry.

**The schema is hand-written JSON Schema, not generated from Zod.** Everything the contract needs,
conditional quote attribution included, is expressible in JSON Schema. The reason for direct authoring is one explicit cross-language contract, with generated
TypeScript types, equivalent format assertions, and a shared acceptance/rejection corpus. Cross-ID
integrity still needs semantic checks and block 3's final `validate` preflight. Published schemas are
immutable numbered artifacts: accepted-shape changes, including optional additions, create the next
integer version. Rejecting unknown fields means an older reader is not forward-compatible with new
producer vocabulary. Both blocks select an explicitly supported schema version and digest.

---

## The product

**One edition serves every reader.** Per-reader personalisation would make language model cost dominate
and scale with the user count. With one shared edition, every cost except bandwidth is fixed, and fixed costs do not care how many
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

**Astro is version 7. Measured 8 September 2026.** Astro 7 requires Zod 4, and its `compressHTML`
default strips newlines between inline elements, which would silently eat the spaces in source rows.
The config sets it explicitly.

**Overflow detection and magnitude have different authority.** Check both scroll axes, nested constrained regions, and page bounds.
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

**Release-1 tests guard invariants and contracts, nothing else. Settled 11 September 2026.** Crash
injection at every transition, fuzzing of every string field, concurrent build isolation, a Python
validator inside the Node package, and pixel-tolerance visual regression were all considered and
rejected: each guards a hypothetical rather than an invariant, and together they are more verification
than block 1 needed. The rule: a test that holds no Section 1 invariant and no published contract is not written. Crash
injection is three boundaries the protocol reduces every interruption to; escaping is one fixed
injection string; visual regression is a manual re-inspection of checked-in reference PNGs before a
renderer change; the Python validator is block 2's test when block 2 exists.

**Type is Newsreader and Libre Franklin. Settled 11 September 2026 by specimen.** The dense fixture
was set five ways and compared in the browser: Playfair Display with Source Serif 4,
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
Danish outlet block 1 collects, ten of them, so adding a Danish outlet to the collector widens what
counts as news. The price is that only Børsen's and Jyllands-Posten's ranked surfaces score prominence;
that term is the weakest in any case.

**Copy is facts first, and colour needs a name on it. Settled 14 September 2026.** Three evaluation
editions read as padded and editorialised because the writer paraphrased RSS teasers faithfully, so
DR's "valggyser" and Altinget's sketch-writing surfaced as the paper's own voice. The writing
guidelines in the [editorial architecture](editorial-architecture.md) require a new fact
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
right: the rivers that argue against it come from inline citation markers, which the design keeps out
of the line. Hyphenation happens at build time rather than in the browser: soft hyphens from TeX
patterns make every browser break identically and make the exception list ours.
Knuth–Plass was rejected for the web because it needs a script or a fixed line width; it remains an
option for the fixed-width device page.

**Attribution is a trailing citation, not a sentence prefix. Settled 11 September 2026.** A page whose
every paragraph opens with "X reports that" reads as a machine repeating itself. Rotating the phrasing
was rejected because rotated synonyms on every sentence read
as generated faster than plain repetition does; dropping attribution was rejected because the
evidence discipline depends on it. Paragraphs and ledes are `{text, sources[]}` in the edition
contract, with publisher ids validated against the story's sources and rendered as a small-caps
marker after the text. Prose names a publisher only when publishers disagree.

**Object storage is a future delivery design, not the local commit protocol.** Immutable prefixes and a single release pointer could replace filesystem primitives. Atomic
single-object writes do not make multiple root/index updates transactional. Hosting remains deferred;
any adapter must define coherent activation and recovery before it is implemented.
Reversed on 30 September 2026 as to hosting, see below; the commit protocol stays local.

**The paper is delivered to S3 and CloudFront at copenhagen-daily.net, unlisted, by the desk. Settled
30 September 2026.** Hosting stopped being deferred without the object-storage adapter ever being
written: block 3's commit protocol stays on the Mac's filesystem, and delivery is a sync of the
finished `live/` directory to a private bucket plus an invalidation, run by the desk after each
activated publish under an IAM user whose only rights are that bucket and that distribution. The
site is public but unlisted, with `noindex` in the page, in `robots.txt`, and in a response header,
because licensing is still open and a shared secret would have shut out the kitchen screen as well.
Activation and recovery remain block 3's, on disk; the bucket is a copy that `verify-live` checks
from outside every morning. The full account is in [AWS delivery](aws-delivery.md).

**The device page is pushed to the kitchen screen's NAS by scp. Settled 30 September 2026.** The
screen reads `todays_news.png` from a share on the house NAS, so after delivery the desk copies
`live/device/current.png` there with legacy `scp -O` (the NAS has no SFTP subsystem), under a host
alias whose key passphrase is in the login keychain. It is a copy of a file already on the site, so a
failed push is notified and never fatal, and the screen keeps the last page it had. The same file is
also on the site at `device/current.png`, which is where TRMNL's Image Display plugin would read it
if the panel is ever pointed at the site instead.
Reversed on 5 October 2026: the panel reads `https://copenhagen-daily.net/device/current.png`, and
the desk's `device_push` phase, its `push-device` action, and the NAS host alias are gone. The web
edition's "View as printed page" link went at the same time; the PNG stays at
`n/<id>/device/page-1.png`, unlinked.

---

## Design

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
the publisher's own placement decision. Coverage is 95 to 99 per cent once every source has section
feeds configured, and zero for a source that has only a latest feed.

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

**Via Ritzau corroborates and never scores. Settled 16 September 2026.** The policy lists it under
`corroborating_publishers`, a third kind beside scoring and linked. A press release is a claim by an
interested party, not a news judgement, so it cannot make a story eligible and counts towards neither
breadth nor prominence; but when a scoring publisher reports a story the release also carries, its
text is attached as evidence for the writer the way a linked publisher's is. The scoring list is nine
Danish outlets, not the ten named in the 14 September entry above, for this reason.

**Wire copy is credited to its agency and linked to its carrier. Settled 30 September 2026.** Every one
of the 21 primaries in the 30 September edition was a Ritzau piece on Kristeligt Dagblad's page. The
cause is mechanical: that outlet's `nyheder` feed carries whole articles (median 2,440 characters of
description against 74 to 197 for the other Danish outlets), so under "the article that supplied the
most of the copy" it wins, and 99 of its 151 articles in the window were Ritzau's. The rule for the
primary is kept, because the fullest evidence is the right thing to write from and the carrier's page
is open to read. What changes is the credit. An article with no byline whose text ends in the agency's
sign-off ("RITZAU", "RITZAU/AFP") is marked `wire: ritzau` by `build` from `wire_agencies` in the
policy, deterministically and never by the editor; all 99 matched and no bylined article did. The page
names Ritzau where it named the carrier, the link still goes to the carrier because the agency
publishes no public page for its wire, and prose that must name a source names the agency. An outlet
whose feed description is a teaser shows no sign-off and is not recognised; TV 2 carries Ritzau copy
this way. Breadth is unchanged and still counts the carrier as a publisher reporting the story;
whether one wire piece should count once across its carriers is open. The field is an optional
addition to a source, so by the rule above it is edition contract version 2; version 1 editions stay
valid and are validated against their own schema.

**Coverage comes from block 1's `health`, not from the export manifest. Settled 30 September 2026.**
The manifest's `coverage_gaps` and `warnings` are written empty, so the desk stopped reading them for
coverage. Before the window is exported the run asks block 1 for `health`, records every configured
feed with its outcome and last check as `feeds.json`, and `build` derives the edition's coverage
status from that list: complete when every feed checked, partial when some failed, unknown when the
list is empty. The same call decides whether a fresh collect is worth running. Block 1 now counts a
failed poll against its feed (`consecutive_failures`), which is what made the health report usable
for this. The manifest fields stay empty rather than being removed, since the bundle schema shipped.

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
five of the six publishers in the sample were running. Cross-publisher breadth is what separates the day's big story from a
well-placed minor one.

**Prominence counts only feeds whose order is editorial. Measured.** Feed ordering was tested on
8 September 2026. The homepage feeds are ranked, as are `nytimes.world`, `borsen.finans`, and
Jyllands-Posten's top-stories feed. Every
`latest` feed and most section feeds, including `dr.indland`, `politiken.indland`, `ft.world`, and
`berlingske.samfund`, are in strict reverse-publication order, so position carries no editorial signal.
Scoring those counted recency twice under another name.
Narrowed on 30 September 2026 to two feeds, see below.

**Only `borsen.homepage` and `jp.topnyheder` are ranked feeds. Settled 30 September 2026.** The policy's
`ranked_feeds` list dropped `borsen.finans` and `nytimes.world`. The NYT feed never counted, since
prominence is scored on scoring publishers only and the NYT is linked; listing it invited the wrong
reading. Børsen's finance feed is a section feed and section feeds are chronological, so it was
double-counting recency like the rest. Prominence is now exactly the two surfaces whose order is a
front-page decision by a Danish desk, and the ten per cent weight on it reads as what it is.

**Unknown prominence is recorded as unknown, not as low.** A story missing from Børsen's homepage feed was
genuinely not front-paged, which is real negative evidence. A story missing from a DR ranked surface tells
us nothing, because DR publishes none. Treating those as the same number would make prominence
untrustworthy.

**Recency is measured in editions, not hours. Measured.** A linear decay over 48 hours barely separates
this morning from yesterday afternoon, which is the distinction a
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
is negligible against the cost of writing the stories. The stronger argument is what it avoids. A
two-stage retrieval design would require an embedding model, a similarity threshold, a candidate-pair
generator, and a cache to keep coherent with all three, and it was fragile precisely where the work is
hardest. Cross-lingual Danish and English matching is where embedding thresholds hurt most and where a
capable general model needs no configuration.

**Return groups, not per-article assignments.** Clusters carry an event description, member identifiers,
and a confidence; anything unmentioned is a singleton. Most articles are singletons, so output stays
short, and long enumerations are where a model drifts or silently drops an identifier. The event
description is what makes a cluster checkable afterwards.

**The cheap signal sits after the model, not before it.** The lexical and temporal checks that would
have proposed candidates validate the model's output instead. Same code, better position: a pre-filter's
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

**The editor is a model and is trusted with judgement. Settled 15 September 2026.** After the first
edition the owner judged good, the question was how much of what made it good to codify. The answer is
the three kinds the architecture names: what the paper is, the hard rules that protect the reader and
the evidence, and the working method. The rest is guidance with reasons, kept out of validators, plus a
golden example, because a capable model given a good example and broad guidelines writes a better paper
than one given a rulebook, and the paper runs few enough calls a day to afford a capable model.

**Block 2 is a Claude Code session under a skill, with the rules in small tools. Settled 24 September
2026.** The API design was costed at roughly eight to thirteen dollars an edition on a capable model,
with the writing calls dominating, against a flat subscription for a session run. The two editions the
owner judged good had in fact been produced by a session reading the handbook, the policy, the golden
example, and the bundle, so the mechanism that made them good already existed and only needed to be
made repeatable. The division the architecture draws is unchanged: judgement in the model, rules in
code. What changed is that the model's part is a session reading and writing phase files, and code's
part is a wrapper of deterministic tools the session must call. The API implementation continues on a
separate branch as a learning exercise. What is given up: structured outputs, caching control, and
per-edition token accounting; what is gained: a smaller block, no framework, and an editor whose
guidance is the documents the owner already edits.

**The checker strikes; it does not rewrite. Settled 24 September 2026.** A rewrite is a fresh
generation and can introduce a new unsupported claim while fixing the old one, so every rewrite needs
another check and the loop needs a termination rule. A strike is deterministic, replayable, and
inspectable, and nothing new can enter. A strike can leave a dangling pronoun or take the opening
sentence, so a story that no longer stands, meaning the opening sentence is gone or more than a third
of the words are, goes back to the editor once with the strikes attached, and a story that fails again
falls to a headline and a link. That is a chief editor who marks up copy and sends it back only when
the marks gut the piece.

**Shorter variants are written on demand, not speculatively. Settled 24 September 2026.** Writing every
variant up front would make the fit loop free of model calls, but most editions need few variants and
each costs output. The loop instead mirrors a desk: block 3 names the shortfall, the editor is asked for
the specific variant the repair order calls for, and the rounds are bounded by the policy's limits with
participation as the final repair.
Reversed on 30 September 2026, see below.

**The editor writes no shorter forms and there is no variant loop. Settled 30 September 2026.** The
device page was made a fit of what exists rather than a negotiation. `build` marks only the lead
required and every other story optional in prominence order; block 3 places as many of the most
prominent stories as fit and omits from the least prominent end, and a device failure leaves the web
edition untouched. The on-demand variant round was dropped because it put a model call inside the
publish, made the run's length depend on the panel, and bought a few extra briefs on a busy day. A
story the panel cannot hold is read on the web, which is the first-class product.

**The checker is a second CLI, Codex, under the same brief. Settled 30 September 2026.** The desk
config names the checker (`checker: claude` or `codex`) and the run accepts `--checker` to override
it; the brief in `VERIFIER.md` is the same either way, and the verdicts record which tool and model
checked. The configured default is Codex, so the copy is checked by a different model from the one
that wrote it; switching is one line and changes nothing downstream.

**Sixteen sources per story is kept, with an inclusion rule.** The cap was reached once, on the Gedser
lead, and only because live-blog entries and a rolling page were counted alongside dated articles. With
one article per publisher unless a second carries distinct evidence, sixteen is every configured
publisher. Raising the cap means a new schema version, which is the right cost for a genuine need and
the wrong reflex for a padded source list.

---

## The desk reads less and writes nothing (2 October 2026)

**The reading view is cut, deduplicated, and split.** Measured on the 1 and 2 October windows:
`window.md` was 177,000 and 223,000 tokens, of which one publisher's full-text feed (Kristeligt
Dagblad) was 51,000 and the six foreign headline-only outlets 60,000; 60 per cent of candidates can
never make a story (`not_in_danish_media`); 276 articles shared an exact title with another, mostly
wire copy carried by several outlets. Descriptions in the reading view are now cut at about 500
characters at a sentence end; across the last five runs, every long-description article the editor
placed in a cluster shared its linking term or name with the cluster inside the title or the first 300
characters, so the cut costs no cluster. Identical text is listed once. The foreign outlets move to
`window-linked.md`. The desk reads about 70,000 tokens.

**Clustering is two passes, both the model's.** The desk clusters the Danish publishers; a subagent
attaches the foreign headlines to the event lines. Linked publishers never score, so a wrong
attachment is cheap, and the validator still sees it. No embeddings, no thresholds; the preference
stated under Clustering above stands, with the context bounded.

**The copy is written by one session per story, run by the runner.** The skill had asked the editor to
delegate each story to a subagent, and the editor wrote everything itself with the whole window in
context; the send-backs that followed were facts from articles the story did not cite. The runner now
writes a brief per story with only that story's evidence, runs a read-only session on it, validates
the answer, assembles the spec, and builds. A send-back rewrites only the stories sent back, each in
its own session. The desk's job ends at the selection and the log.

**Berlingske's section comes from its category tags.** The samfund feed carries world, politics and
domestic news together and had mapped every article to `denmark`, so on 1 October all 24 eligible
candidates had the same section weight and the section signal did nothing. The feed now maps to
nothing and `category_sections` maps the publisher's own tags.

**Memory holds only editions cut off before this run.** A rerun or a second printing for an earlier
cutoff saw the editions after it and read its whole window as already covered.

**Measured on dry reruns of the 1 and 2 October editions, same cutoffs.** The desk read 69,000 and
75,000 tokens instead of 177,000 and 223,000 and cost $6.01 and $5.48 instead of $6.84 and $10.07.
The writers took 21 and 23 sessions, a median of five turns and 20 seconds each, $5.77 and $5.79 in
all, with no answer needing a second attempt. Neither rerun produced a send-back, against one of the
two published runs; strikes were 3 and 0 against 0 and 1. The whole run cost $11.78 and $11.27
against $8.06 and $10.07, so the per-story sessions cost about a dollar to four more than the single
editor did, bought with the guarantee that no story's copy rests on another story's evidence. Wall
clock was about the same, 16 minutes. The checker's advisory notes rose from one to four per edition,
all the same fault: an outlet named in prose for a fact of record; the writer's brief now says so
explicitly. Berlingske's samfund articles split into world, Denmark and politics instead of all
Denmark, and the ranking's diversity note moved from "denmark holds 24 of 24" to 18 of 24. The 1
October rerun led with the grid tariffs, the ranking's first, where the published edition had
promoted the Flydubai cockpit stabbing from eleventh on breadth; the desk's own log says the world
weight buried three broadly covered foreign stories, which is the open question on section weights.

**Five review findings, all taken** ([the review](reviews/editorial-writer-split-review-2026-10-02.md)).
The writer's isolation was a prompt, not a boundary: it had the repository added and the run
directory as its working directory. It now starts in the story's own directory with nothing added,
which a headless session cannot read outside of (checked live: the read was refused), and the brief
carries the skill, the style guide and the guidelines. A retry re-recorded every input and so could
adopt evidence changed mid-phase as the baseline; it now records its own brief only. A title alone
had counted as the same text, hiding updated descriptions on rolling pages; the same headline over a
different description now keeps it. Writers took one wall clock computed before the queue; each
attempt now takes what the run has left. A half-written story file blocked recovery; cached copy is
now validated, bound to its brief, and written atomically.

---

## Clarity, and the one fact from outside the evidence (3 October 2026)

The 2 October lead said "as passenger plane crossed Borris" and never said what Borris was. The style
guide now carries a clarity rule modelled on The Economist: every name, place, institution or term a
reader outside Denmark could not place is explained on first mention in the body, after the name and
set off by commas, the well known included ("Elon Musk, Tesla's chief executive"), nested when one
explanation is not enough; headlines avoid such terms where a plainer phrase carries the news, and
when the term is the story the body's first sentence explains it. Kristeligt Dagblad's own copy on
the Borris story did exactly this.

**Such an explanation may come from the writer's knowledge, and it is verified.** It is the only
fact allowed from outside the evidence. The writer declares each one with the Wikipedia article that
confirms it; the runner fetches the article's summary (the only host a run reaches besides delivery,
and never from a session, which keeps the boundary in AGENTS.md as it was); the summary joins the
story's evidence as a reference row; the checker verifies the explanation against it and may use it
for nothing else. Wikipedia is treated as authoritative for identifying facts of this kind. A lookup
that fails leaves the explanation unsupported, so it is struck or rewritten, never trusted.

---

## The alpha starts at No. 1 (6 October 2026)

The paper moved from pilot to an alpha shared with friends, and the pilot's editions were removed
rather than hidden, so the site, the store and the desk agree on what has been published. The 19
pilot editions, the second printing, and the Tuesday 6 October edition as first published (No. 20)
were deleted from the publish root and the bucket, and their run directories from the tree (they
remain in git history and in a tarball outside the repository). The same checked copy of 6 October
was published again as `2026-10-06-morning` with the number 1, so numbering restarts from it. The
thread registry was kept: readers never see it, and it spares the first editions repeating stories
the pilot already ran. The golden example and the test fixtures, which are working parts of the
newsroom rather than editions, are unchanged.

---

## Feeds stop taking turns: revisions, not observations, decide the merge (9 October 2026)

**Measured.** The database grew about 550 MB a day, and `article_versions` was the largest table:
454,040 versions between 1 and 9 October for about 15,000 distinct article texts. The merge ranked
feeds of equal `description_priority` by observation time, so an article carried by several feeds
changed winner every time another feed was polled. The winner's feed was hashed as
`description_source`, and WSJ's per-feed `mod` link parameter and "Opinion | " title variants were
too, so every rotation wrote a version. NYT, FT, Børsen and WSJ accounted for most of it.

Ranking feeds by a fixed order instead stops the rotation, but it freezes a stale headline if the
preferred feed drops an article that is then edited in another feed. Ranking by when each value
first appeared keeps edits but rewards whichever feed was polled second. That would override the DR
contract (section descriptions beat latest descriptions) and settle WSJ's two titles by polling order.
Restricting the merge to feeds that still carry the article also works, but it turns an article
leaving a feed into an event that rebuilds would have to reproduce.

The chosen rule records, per feed and field, when the value last *changed within that feed*. A feed's
first values only introduce the article. Across feeds the newest revision wins, and values no feed
has revised follow priority and order. `description_source` names the feed whose description won and
is no longer hashed, and WSJ `mod` leaves canonical URLs; the merge re-derives canonical URLs from raw
URLs with the current rules, so history and new polls compare equal. Replaying all 2.96 million retained
sightings gives 19,383 versions for 1–9 October instead of 454,040. The remaining cost is accepted:
an already-edited value that first appears in a feed which never carried the old one is an
introduction, and it loses to a stale value from a higher-ranked feed or an older revision. Priorities stopped being
absolute too: an edit in the DR latest feed now beats an unrevised section description until the
section feed changes. The analysis and the replay were checked independently with Codex.

---

## Deferred, with gates

**Edition revisions and correction notices.** Designed in the [roadmap](roadmap.md). The first release
publishes each edition id once and corrects mistakes in the next edition. Gate: a real correction is
needed on a published edition and the next-edition workaround proves inadequate.

**Headlines-only degraded edition.** Designed in the [roadmap](roadmap.md). Release 1 keeps the last
activated edition when a run fails. Gate: a run has failed on a morning that mattered.

**Multi-page device output.** Designed in the [roadmap](roadmap.md). The first release renders exactly one
device page, so there is no page budget, no inside-page composition, and no playlist coordination. Gate:
a week of material optional omissions or repeated required-story device fit failures. Required
stories cannot be silently omitted from a successful device edition.
Since 30 September 2026 only the lead is required (see Clustering and threads, the entry on shorter
forms), so the second half of that gate is a lead that does not fit.

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
reader is a very different position from a public page redistributing summaries of sixteen publishers'
reporting. Charging for it would be a further
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
Closed on 30 September 2026 from the other side: the desk derives coverage from `health` instead
(see Editorial signals). The manifest fields stay empty.
