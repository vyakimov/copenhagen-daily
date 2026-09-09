# Deferred: visual prominence capture

**Status: to do in the future. Not authorized to build.** Recorded 9 September 2026 so the reasoning
survives. Nothing in the current plans depends on this. Companions:
[Block 2 editorial architecture](news-editorial-architecture-plan.md) and the
[decision log](decision-log.md).

## The gap this would close

Prominence answers "how prominently did this publisher display the story", which is the publisher's own
judgment of importance and the one signal breadth cannot supply. Breadth says many publishers cared.
Prominence says one publisher cared a great deal, which is how a single-publisher scoop gets recognised
instead of buried.

Today only three of six publishers supply it honestly. Feed ordering was tested on 8 September 2026:
the three homepage feeds are editorially ranked, as are `nytimes.world` and `borsen.finans`, while every
`latest` feed and most section feeds are in strict reverse-publication order and therefore carry no
placement signal at all. DR, Politiken, and Berlingske publish no ranked feed, so their prominence is
recorded as unknown.

## Why the obvious fixes were rejected

**Per-publisher markup extraction** was assessed against the three Danish homepages on 9 September 2026.
Politiken is tractable, exposing `data-article-id` in document order plus `data-page-section` naming the
layout slot and an explicit `data-is-super-article` flag. Berlingske hides its content in a `__NEXT_DATA__`
blob with no article-shaped nodes at reasonable depth. DR is server-rendered but carries no semantic
attributes and uses hashed class names that change on every build, so a scraper would break silently and
return plausible wrong numbers rather than an error. One publisher out of three is not worth a subsystem.

**Reading rendered markup with a browser** solves nothing that plain HTTP does not. All three homepages
are server-rendered, and hashed class names are hashed in a rendered DOM too.

## The shape worth building

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

## Choosing a tool, when the time comes

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

At six captures per edition the volume is too small for per-request cost to matter, so the decision turns
on who handles bot mitigation and whether routing publisher URLs through a third party is acceptable.
Some hosted services also return structured extraction, which would substitute for the vision model but
reintroduces the markup-reading fragility this design exists to avoid.

## What remains genuinely costly

Getting to the page. Every Danish site presents a consent wall, and NYT and FT add paywalls and possible
bot challenges. That is per-publisher work, though it is one-time session state rather than selectors
that churn with redesigns. Rendering pages to extract editorial ordering also sits further from a
publisher's terms than reading their feed, which compounds the redistribution question recorded elsewhere.

Prominence would also stop being deterministic, moving from a computed number to a retained model
judgment. The existing mitigation applies: retain the accepted response and its inputs.

## The gate

Do not begin until the editorial log shows a recurring, named complaint that single-publisher scoops are
being buried, across at least several weeks of real editions. Prominence carries a tenth of the ranking
weight, the correction restricting it to ranked surfaces has not yet been measured in production, and
building an acquisition subsystem for the smallest term before that evidence exists is the wrong order.
