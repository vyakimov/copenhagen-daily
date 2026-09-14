# Roadmap

Work that is designed but not authorized to build. Each item states the gap it closes, the approach
settled for it, and the gate that must be met before it starts. Nothing in the current plans depends
on anything here. Companions: [Block 2 editorial architecture](news-editorial-architecture-plan.md),
[Block 3 publishing architecture](news-publishing-architecture-plan.md),
[Block 3 implementation](news-publishing-implementation-plan.md), and the
[decision log](decision-log.md).

---

## Sources without public RSS

**Status: deferred. Ignore sources without public RSS feeds for now.** Settled 14 September 2026.

Zetland, Weekendavisen, AP, and Reuters are candidates to revisit. Hosted services such as
[RSS.app](https://rss.app/), [Feeder](https://feeder.co/), and
[Inoreader](https://www.inoreader.com/) can generate feeds from public web pages, potentially filling
these gaps while existing first-party RSS collection stays direct. RSS.app extracts entries
automatically or through a visual builder, optionally renders JavaScript, and periodically updates a
hosted RSS feed. Feeder explicitly offers AI-assisted extraction; RSS.app's use of an LLM was not
established. This buys managed extraction and hosting, not complete wire coverage or subscriber text.

RSS.app is the first trial candidate if this is revisited; it advertises AP and Reuters support, but
actual output for all four publishers remains untested. Feeder and Inoreader are more attractive if a
personal reader is also wanted. Check current pricing and external-feed export limits before choosing.
Weekendavisen's Google News sitemap, already recorded in the source contracts, is a possible
first-party alternative to generated RSS.

**Gate:** explicitly decide that missing-source coverage warrants expanding the first-party RSS policy.
Then trial output against public listings for missed articles, stable URLs/IDs, accurate dates, usable
teasers, and refresh/item-window limits. Retain third-party provenance; generated ordering is not
publisher-prominence evidence, and generated summaries are not publisher-authored text. Local XML
processing can remain deterministic, but upstream extraction adds uncertainty and page-change failures.
No integration or scraping work is authorized by this note.

References: [RSS.app extraction and limitations](https://help.rss.app/en/articles/10522151-generator-and-builder-faq),
[Feeder AI feeds](https://feeder.co/product/ai-feeds),
[Feeder RSS/JSON export](https://feeder.co/help/rss/how-to-export-your-posts-as-rss-and-json-feeds/).

---

## Edition revisions and correction notices

**Status: deferred. Not in the first release.** Settled 11 September 2026.

### The gap

The first release publishes each edition id exactly once. A mistake is corrected in the next edition,
and the erroneous edition stays as published. That is acceptable for a pilot and wrong for a newspaper:
a correction should be attached to the piece that was wrong, at the address people already have for it.

### The approach

Standard newspaper practice: the erroneous text stays where it was published, and a correction is
appended rather than the record being replaced. This is achieved without weakening the immutability of
the store, because the plan already has two layers and the notice belongs in the mutable one.

**Revision-qualified permalinks.** Every revision of an edition has its own immutable bundle at
`n/<edition-id>/r<revision>/` and its own permalink at `/n/<id>/r<N>/`. Every link the site emits uses
the qualified form, so a link a reader copied stays pointing at exactly what they read, including a
critic's link to an error. The bare `/n/<id>/` becomes a shell redirect to the newest revision. The
archive and the latest pointer follow the newest revision. The device pointer advances to the newest
revision that produced pages.

**The notice lives in the release, not the bundle.** The web page template reserves a marked placeholder
near the masthead. When the release is built, any revision that has been superseded has its page written
into the release as a derived copy rather than a hard link: the store's HTML with a notice substituted
into the placeholder. The notice says when the edition was revised, what changed, and links to the new
revision. Its text comes from the newer bundle, which carries an optional `correction_note` from block 2
in the contract. Every other file stays a hard link. The manifest keeps hashing store bytes; `verify`
regenerates the derived copy and compares it.

What weakens, deliberately and in one place, is the rule that the served page is byte-identical to the
store, and only for superseded revisions. Immutability of the record is untouched: the store bundle is
still published by one rename, read-only, and hashed.

**Why not edit the original.** Editing the bundle stales the manifest hashes, makes `verify` learn which
edits are legitimate, turns the read-only mode into decoration, and loses the one-rename publication
guarantee, all to write one sentence the release layer can write for free. It is also less honest to a
critic: an edited original invites the question of what else was edited. A hashed original plus a
visibly separate notice answers it.

### What it costs

The contract gains `edition.revision` and an optional `correction_note`. The store path gains one
segment. The web template gains the placeholder. The release build gains one substitution step. `verify`
gains one branch. The acceptance criterion that re-publishing an id fails becomes re-publishing an id
and revision fails. Block 2 gains the ability to re-issue an edition with an incremented revision through
its own validation boundary, which is also how human overrides would enter: an edited headline or a
pinned story becomes a recorded override that creates a new revision, never an in-place rewrite of
generated JSON.

### The gate

A real correction has been needed on a published edition and the next-edition workaround was found
inadequate in practice. Do not build it speculatively.

---

## Multi-page device output

**Status: deferred. Not in the first release.** Settled 11 September 2026.

### The gap

The first release renders exactly one device page. On a busy day the fit policy drops callouts and then
omits optional stories, so the panel shows less of the edition than the web does. A second page would
let the panel carry more of the paper. The reading-time cost is real: a page is read at arm's length,
and a two-page paper on a display that shows one page at a time is two separate visits.

### The approach

**An ordered list of pages, each with its own composition.** Page 1 keeps the three lead compositions.
Inside pages need their own catalog entries, because they have no lead: an *inside* composition with
three to five medium-length secondaries and a *briefs* composition that is briefs-heavy. Page 2 without
a composition of its own is not a design; it is page 1 with a hole where the lead was.

**Fit policy gains a budget.** `fit_policy.page_budget` and `page_maximum`, defaulting to 1 and 2. The
repair ladder gains a step between composition substitution and omission: move the story to a later
page within the maximum, restarting the ladder. Repairs apply page ascending, then slot order. Never
split a sentence across pages; a story moves whole. The receipt and the composition record gain a
`page` per story and a `pages` count.

**File naming is already reserved.** `device/page-1.png` is numbered so that `page-2.png` is additive.
Each page is its own document at its own URL; never stack pages in one document and clip.

**Delivery through TRMNL playlist slots.** One Image Display instance per active page, in reading order,
with page number, page count, edition date, and edition ID visible on every page. Publication and device
refresh are separate events, and a playlist is not a transactional document viewer: the hosted service
may refresh slots at different times. With a fixed two-slot configuration, generate a truthful "end of
edition" second image when an edition has only one page, so the panel cannot keep showing yesterday's
page two. Verify multi-page refresh and next-screen navigation on the actual firmware before relying on
it.

### What it costs

Two new compositions with device trials at physical size, the page dimension through the fit engine,
receipt, composition record, and manifest, a second delivery slot, and the test cases a one-page paper
does not need: a two-page edition, a one-page edition after a two-page day, and the end-of-edition slot.

### The gate

A week of real editions in which optional stories are omitted often enough to matter, or required
stories cause repeated device fit failures, judged against the reading-time cost of a second visit.
Required stories are never silently omitted from a successful release-1 device edition.

---

## Multiple titles

**Status: deferred. Not in the first release.** Settled 11 September 2026.

### The gap

The first release is one newspaper. A second remit, for example a sports-and-culture paper beside the
news paper, is a second title: its own policy, schedule, masthead, archive, and panel image, publishing
one public edition that everyone gets.

### The approach

**Block 2 shares the expensive work.** Collection, clustering, and matching run once across all titles.
Each title's policy selects and orders from the shared candidate set, which is ordinary ranking code
with no model call in it. Selection happens before writing: the selections are unioned, each distinct
story is written exactly once, and each title's edition draws its own subset from that written pool. A
second title therefore adds writing cost only for stories the first did not run and no matching cost at
all. Repeat-suppression memory and selection state are keyed by title, because two titles are two
publications with their own continuity, and a story may legitimately appear in both. Relevance
assessment caches per title, since it depends on the title's policy; matching and writing cache across
titles. Each title has its own editorial policy file and section-vocabulary table. Titles publish
independently: one title's failure must not delay or block another's edition.

**Block 3 puts the title in the path.** `config/title.yaml` becomes `config/titles.yaml`, keyed by title
id, and a title block 3 does not know is `resource_not_found` rather than a guess. Edition ids are unique
only within a title, so the store and release gain a `<title>/` prefix:

```text
store/<title>/n/<edition-id>/      bundles, unique because the title is in the path
live/<title>/index.json            that title's activated release index snapshot
store/a/<layout-version>/          shared assets stay title-independent
live/<title>/                      that title's site root, latest.json, archive/, go/
live/<title>/n/<edition-id>/       hard links into the store
live/<title>/device/current.png    that title's panel image
```

Every pointer answers its question per title, so a reader of one title gets that title's latest edition
and a panel showing one title gets that title's latest page. Web permalinks gain the same segment, so a
link identifies the paper as well as the issue. Titles are independent all the way down: one title's
failed build cannot disturb another's, and adding a title is a config entry plus a masthead, not a code
change.

### What it costs

One path segment through the store, release, permalink routes, and `verify`; the config file keyed by
id; per-title keying of block 2's memory and cache tables; a second policy file and section table; and
a test that two titles publishing the same edition id on the same day do not collide.

### The gate

A second remit is actually wanted. Do not build the prefix for one paper.

---

## Visual prominence capture

**Status: deferred. Not authorized to build.** Recorded 9 September 2026.

### The gap this would close

Prominence answers "how prominently did this publisher display the story", which is the publisher's own
judgment of importance and the one signal breadth cannot supply. Breadth says many publishers cared.
Prominence says one publisher cared a great deal, which is how a single-publisher scoop gets recognised
instead of buried.

Today only Børsen supplies it in a way that counts. Feed ordering was tested on 8 September 2026: the
three homepage feeds are editorially ranked, as are `nytimes.world` and `borsen.finans`, while every
`latest` feed and most section feeds are in strict reverse-publication order and therefore carry no
placement signal at all. Since 14 September 2026 only the Danish scoring publishers contribute to
prominence, which removes the international homepage feeds from the calculation. Of the nine Danish
scoring publishers only Børsen (homepage feed) and Jyllands-Posten (top-stories feed) publish a ranked
feed; the other seven are recorded as unknown. Capturing the Danish homepages is therefore the whole of
this item.

### Why the obvious fixes were rejected

**Per-publisher markup extraction** was assessed against the three Danish homepages on 9 September 2026.
Politiken is tractable, exposing `data-article-id` in document order plus `data-page-section` naming the
layout slot and an explicit `data-is-super-article` flag. Berlingske hides its content in a `__NEXT_DATA__`
blob with no article-shaped nodes at reasonable depth. DR is server-rendered but carries no semantic
attributes and uses hashed class names that change on every build, so a scraper would break silently and
return plausible wrong numbers rather than an error. One publisher out of three is not worth a subsystem.

**Reading rendered markup with a browser** solves nothing that plain HTTP does not. All three homepages
are server-rendered, and hashed class names are hashed in a rendered DOM too.

### The shape worth building

Capture the page and have a vision-capable model read it. This is the one approach that is
publisher-agnostic: one prompt serves all six, a redesign does not break it, and any page legible to a
person stays legible to the model. It also measures the actual quantity, since prominence genuinely is
size, position, imagery, and whether a story sits above the fold. Every markup signal is a proxy for that.

Three constraints make it sound rather than merely clever.

**Put the browser in its own component, not in block 2.** Both architecture plans state that the
editorial model has no browser and no acquisition tools, and that neither the model nor the publishing
browser fetches publisher pages. That is a containment boundary. Untrusted publisher text currently
reaches block 2 as data from a file it cannot influence; giving block 2 a browser would make prompt
injection from a publisher page a live path. Instead add a small capture component that owns the browser,
runs on a schedule, holds no editorial model credentials, talks to nothing downstream, and emits ranked
observations into the appearance records block 1 already produces. Block 1 stays browser-free and block 2
stays fetch-free.

**Let it rank only what RSS already collected.** The model returns an ordered list of headlines; code
matches each to a known article by URL or title and discards anything unmatched. The capture can reorder
the newspaper's existing candidates and can never introduce content into it. This is both a cheap
validator and the property that makes the whole idea safe.

**Capture once per edition, immediately before the run.** Front-page position is wanted at deadline, not
as a time series. Six renders and six model calls per edition is negligible. Continuous polling would be
hundreds of captures a day and easily the most expensive thing in the system, spent on the smallest term
in the ranking formula.

### Choosing a tool, when the time comes

No preference is expressed here between self-hosted browser automation and a hosted capture service. The
requirement is a rendered page image plus a stable way past consent and paywall interstitials. Decide on
these axes rather than on a product name:

| Axis | Self-hosted browser | Hosted capture service |
|---|---|---|
| Consent walls, bot challenges, IP reputation | Yours to solve, and the hardest part | Largely handled, which is the main thing being bought |
| Third party sees the target URLs | No | Yes, and it fetches on your behalf, which changes the posture toward publishers |
| Marginal cost | None beyond compute | Per request, negligible at six per edition |
| Failure surface | A browser to pin and keep working | An external dependency and its availability |
| Reuse | Block 3 already pins a browser, though for a different purpose and under a different boundary | New dependency |

At three or four captures per edition the volume is too small for per-request cost to matter, so the
decision turns on who handles bot mitigation and whether routing publisher URLs through a third party is
acceptable. Some hosted services also return structured extraction, which would substitute for the vision
model but reintroduces the markup-reading fragility this design exists to avoid.

**Hosted services to explore first: Tavily and Firecrawl.** Both fetch and render a URL on your behalf
and return the page as text, structured content, or a screenshot, and both are built to get past the
consent walls and bot challenges that are the costly part here. Evaluate them on the axes above and on
three specific questions: whether they return a full-page screenshot of the rendered homepage, which is
what the vision model needs; whether a Danish consent wall is dismissed or captured as the page; and
whether their terms and the publishers' terms permit fetching a homepage on a schedule. Their extraction
output is a secondary interest, since the design reads the image rather than the markup. Neither is a
commitment; the self-hosted browser block 3 already pins remains the comparison.

### What remains genuinely costly

Getting to the page. Every Danish site presents a consent wall, and NYT and FT add paywalls and possible
bot challenges. That is per-publisher work, though it is one-time session state rather than selectors
that churn with redesigns. Rendering pages to extract editorial ordering also sits further from a
publisher's terms than reading their feed, which compounds the redistribution question recorded elsewhere.

Prominence would also stop being deterministic, moving from a computed number to a retained model
judgment. The existing mitigation applies: retain the accepted response and its inputs.

### The gate

Do not begin until the editorial log shows a recurring, named complaint that single-publisher scoops are
being buried, across at least several weeks of real editions. Prominence carries a tenth of the ranking
weight, the correction restricting it to ranked surfaces has not yet been measured in production, and
building an acquisition subsystem for the smallest term before that evidence exists is the wrong order.
