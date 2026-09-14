# Detailed implementation plan: broadsheet publishing

Status: implementation plan, 8 September 2026, revised 11 September 2026 after design review and
again the same day for handoff: the repository is relocated, the contract's field shapes are fixed by
a golden document, and test scope is bounded to the invariants. Its architecture companion is
[Block 3: Broadsheet publishing architecture](news-publishing-architecture-plan.md), which is
authoritative on boundaries where this document is silent. The upstream contract is defined in
[Block 2: Newspaper editorial architecture](news-editorial-architecture-plan.md). The visual
direction is in [`design/README.md`](design/README.md).

## 1. How to use this plan

Block 3 turns one accepted edition from block 2 into a newspaper. It is a module an LLM in block 2
calls, so its interface is a JSON-in, JSON-out command, and its failures name the slot that overflowed
and by how much, so block 2 can shorten copy and retry rather than guess.

Complete the provisioning prerequisite in Section 16, then implement the work packages in the three
handoff batches Section 16 defines. WP 14 is a post-release local adapter. Each package names the
files to create, the behavior to implement, the tests to add, and the condition that makes it
complete. Sections 3–15 are the normative specification; work packages cross-reference them rather
than repeating them. `contracts/examples/minimal.json` already exists and fixes the field names and
nesting of the edition contract: Section 5 defines meaning, the file is authoritative on spelling.

Two steps need the owner and cannot be done by an implementing agent: the physical device trials in
WP 3 and WP 12. When a package reaches one, record what is ready, stop, and report. Do not wait for
hardware, and do not mark the package complete.

These invariants outrank any conflicting detail below.

1. Block 3 never calls a language model. It selects among the copy variants block 2 supplied and
   measures boxes. It does not rewrite, shorten, or re-order approved copy, and it never composes
   callout text.
2. The renderer visits no publisher URL, loads no remote font, script, or image, and executes no HTML
   or Markdown emitted by a model. Every contract string is escaped before it reaches a template.
3. The web edition is the product. It carries every story and callout the edition accepted, at full
   approved length. Only the device edition may omit anything, and nothing in the web edition is
   constrained to keep parity with the panel.
4. A published edition directory is immutable, and an edition id is published at most once. There are
   no edition revisions: a mistake is corrected in the next edition. A design change or a renderer
   upgrade never rewrites an archived edition's files.
5. The device edition is exactly one page of exactly 1872 × 1404 pixels, PNG colour type 0 at bit depth 4, at most 16 distinct
   grey levels, never dithered.
6. Stdout is one compact key-sorted JSON object per invocation. Diagnostics go to stderr.
7. Every mutating action supports `--dry-run`. Validate inputs and configuration before temporary
   work, and validate all outputs before committing publication changes. Dry runs may use temporary
   files and locks, but never change committed bundles, release history, or the live pointer.
8. Type sizes are fixed by declared role/composition tokens; margins, rule weights, and palette are
   fixed. No value adapts to copy length. Only composition, role counts,
   callouts, and structural elements vary between editions, and they vary from editorial signals.

The first release ends when WP 1–13 (including WP 0's retained experiments) pass: one real edition
has been read on the device and the seven-edition variation review is complete.

## 2. Product boundary

**In scope.** Validating an edition contract; building the web edition with per-edition permalinks, an
archive index, and a latest pointer; choosing a device composition and fitting stories to it by
measurement; capturing the device page and converting it to 16-level PNG; publishing an immutable
bundle atomically; returning a publication receipt and a fit report to block 2.

**Out of scope for the first release.** Publisher photography, a CMS, Paged.js, PDF output, a portrait
device profile, hosting, TRMNL account configuration, and any network delivery. The delivery adapter is
an interface and a post-release local verification path only. The exceptions are the early typography
trial and WP 12's device check, each of which is a
person's action: the user places the PNG at a URL they control and enters it into the Image Display
plugin by hand. Block 3 uploads nothing and touches no account. These plans authorize no public posting.

**Repository.** The `copenhagen-daily` repository, which holds all three blocks. Block 3 occupies
`publisher/`. `editorial/` is reserved for block 2's Python application, and `ingest/` holds block 1,
relocated there on 11 September 2026 with its wrapper at `ingest/gather_news.sh`. No block claims the
repository root; the root `AGENTS.md` states the cross-block boundaries. `ingest/` is unchanged by
this plan and gains no Node dependency; the Node toolchain is confined to `publisher/`.

## 3. Locked technical decisions

Versions below were checked on 8 September 2026. Do not invent versions in advance; resolve once, pin
exactly, and commit the lockfile.

| Decision | Choice | Evidence |
|---|---|---|
| Web framework | Astro 7.3.1 | Current release; Astro 6 shipped March 2026, Astro 7 on 22 June 2026 |
| Device rendering | **Plain TypeScript templates, no Astro** | Section 8 |
| Runtime | Node 26.5.0, `engines: ">=26 <27"` | Astro 7 requires Node ≥ 22; Node 26 strips TypeScript types natively. Imports carry explicit `.ts` extensions; `tsconfig.json` sets `allowImportingTsExtensions` with `noEmit`, and `erasableSyntaxOnly` |
| Browser | Playwright 1.63.0, `channel: 'chromium'` | The default headless shell is a stripped build with a different font stack |
| Contract validation | Hand-written JSON Schema, validated with Ajv | Section 5. TypeScript types are generated from the schema, not the reverse |
| Astro content collection | Zod 4 | Astro 6 upgraded to Zod 4 and dropped Zod 3. Used only for content already validated at the CLI boundary |
| Image conversion | ImageMagick 7.1.2-31 | Verified on this machine |
| Package manager | npm 11.17.0, `npm ci` only, `package-lock.json` committed | — |
| Fonts | Newsreader and Libre Franklin, OFL, vendored variable WOFF2 | Section 14 |
| Persistence | Files only; no database | Immutable bundles, release snapshots, and a durable publication journal; Section 13 |

Rendering depends on the accepted contract, configuration, assets, and pinned environment. Publication
also reads retained release state. The file journal makes activation recoverable without a database;
an immutable bundle alone does not establish that readers could reach it.

## 4. Target repository layout

```text
copenhagen-daily/
  README.md
  AGENTS.md
  ingest/                        Block 1 (Python). No Node dependency.
  editorial/                     RESERVED for block 2 (Python). README only for now.
  publisher/
    publish_news.sh              allowlisted entrypoint, mirrors gather_news.sh
    package.json                 one package, no workspaces, exact pins
    package-lock.json
    tsconfig.json
    .nvmrc
    bin/publish_news.ts          CLI entry; Node runs .ts directly, no build step
    config/title.yaml            the one title: masthead, device profile, asset theme
    contracts/                   HAND-WRITTEN. The published interface block 2 builds against.
      edition-contract.v1.schema.json
      publication-receipt.v1.schema.json
      fit-report.v1.schema.json
      composition.v1.schema.json manifest.v1.schema.json device-artifact-result.v1.schema.json
      examples/                    the ONLY edition documents; both blocks test against these
        minimal.json  dense.json  sparse.json  long-headline.json  danish.json
        all-callout-kinds.json  required-overflow.json  partial-coverage.json
        rejections/                one invalid document per Section 5 invariant, with expected code and pointer
    src/
      contract/                  SHARED by device, web, and cli
        edition-contract.ts      types generated from the JSON Schema; Ajv validator
        composition-record.ts    the frozen device composition
        fit-report.ts            what goes back to block 2
        manifest.ts  envelope.ts  version.ts
      device/                    DEVICE ONLY. No Astro, no Vite.
        catalog/ lead-wide.ts lead-tall.ts lead-centred.ts catalog.ts
        render.ts                frozen composition -> one full HTML document string
        server.ts                in-process loopback http server, port 0
        measure.ts               Playwright setup and the single-evaluate probe
        fit.ts                   the bounded repair loop
        capture.ts  quantize.ts
      publish/
        store.ts release.ts manifest.ts hash.ts atomic.ts lock.ts recovery.ts
      cli/
        main.ts args.ts
        actions/ list-actions.ts validate.ts fit.ts render-device.ts
                 build-web.ts publish.ts recover.ts receipt.ts verify.ts doctor.ts check.ts
    assets/                      SHARED design language
      css/tokens.css             palette, @font-face, type faces
      css/device.css             device geometry and type scale
      css/web.css                web geometry, accent, breakpoints
      html/escape.ts callout.ts source-row.ts kicker.ts
      fonts/*.woff2  fonts/OFL.txt  fonts/fonts.lock.json
    site/                        WEB ONLY. The Astro root.
      astro.config.mjs
      src/
        content.config.ts
        layouts/Broadsheet.astro
        components/ Masthead.astro Story.astro Callout.astro SourceList.astro Folio.astro
        pages/
          index.astro
          n/[edition]/index.astro
          archive/index.astro
          go/[edition]/prev.astro  go/[edition]/next.astro
    tests/ unit/ fixtures/       non-edition fixtures only: CSS cases, WP 0 measurement cases, crash scripts, reference PNGs
    var/                         gitignored: runs/<run-id>/, publish-root/
```

One package, no workspaces: one lockfile, one `node_modules`, no hoisting nondeterminism. Astro runs as
`node_modules/.bin/astro build --root site`; `npx` is never used at runtime because it may download.
Enforce the module boundary with a test that greps imports: `device/` must not import from `site/`,
and `site/` must not import from `device/`.

## 5. The edition contract

### Ownership and the shape of the artifact

**Block 3 owns this contract**, because block 3 is what can or cannot render a thing. The set of story
roles, callout kinds, and compositions is a statement of layout capability, not an editorial preference.
Adding a callout kind is therefore a block 3 change: the schema gains a variant and the renderer gains
the code to draw it, in one commit. Block 2 then composes within whatever block 3 declares possible.

The artifact both blocks use must be **the same file, not a translation of it**. `contracts/` holds
hand-written JSON Schema. Block 3 validates every incoming edition against it with Ajv. Block 2
validates its own output against the identical file with Python's `jsonschema` before writing. Block 3's
TypeScript types are generated *from* the schema with `json-schema-to-typescript`, so the types follow
the contract rather than defining it.

Author the boundary in JSON Schema Draft 2020-12, with explicit `$schema` and versioned `$id`, rather
than relying on translating runtime refinements. Conditional requirements such as a quote's speaker
are expressible with `oneOf` or `if`/`then`; put these in the schema. Cross-reference integrity and
uniqueness by story ID still need semantic validation. Reject unknown fields throughout, disable Ajv
coercion/default insertion/removal of fields, and enable equivalent format assertions in Ajv and
Python `jsonschema`. Timestamp validation includes calendar validity and the exact six-digit UTC form,
not merely a permissive `date-time` format. All schema references resolve locally; no network lookup.

Astro's collection schema is an internal adapter and must preserve validated fields without silently
stripping them. It carries no additional public-contract rules.

`contracts/examples/` holds golden edition documents. Both blocks load them in their test suites: block
3 asserts it can consume them, block 2 asserts it can produce documents like them. A shared rejection
corpus covers schema and semantic violations, with expected codes and JSON pointers. Both blocks run
the corpus; block 2 also calls `publish_news.sh validate` as its final preflight before publication.
Block 3's own suite runs the corpus under Ajv only. Running it under Python `jsonschema` is block 2's
test, added when block 2 exists; the publisher carries no Python environment. Equivalent schema
acceptance alone is not equivalent semantic validation.

### Versioning

Published schemas are immutable numbered artifacts. Any change to accepted document shape, including
an optional field or a new callout kind, creates the next integer `schema_version` and a new file.
Block 3 declares supported versions and their schema digests through `version` and `schema`; block 2
selects a supported version before writing. Older readers reject newer versions with
`contract_unsupported_schema_version`. A new renderer may retain older validators and normalize them
internally, preserving the original accepted document in the bundle. Do not imply forward compatibility
when unknown fields are rejected. Receipt, fit-report, composition, and manifest schemas are independently
numbered and immutable as well.

Unknown fields are rejected. Every timestamp is RFC 3339 UTC with six fractional digits and a `Z`,
matching block 1.

### Identity, presentation, coverage

| Field | Meaning |
|---|---|
| `schema_version` | Integer literal `1`. Block 3 refuses versions it does not implement. |
| `title` | The publication this edition belongs to. Must equal the single title id in `config/title.yaml`; anything else is `contract_invalid`. One string, kept so that a second title is additive later. |
| `edition.id` | Stable identity. Published at most once. |
| `edition.date`, `timezone`, `language`, `cutoff_at`, `generated_at` | Display date, display zone, output language, the "news through" time, and editorial generation time. |
| `edition.name`, `edition.number` | Masthead ear text such as "Afternoon brief", and the edition number. |
| `presentation.preferred_composition` | Optional hint: `lead-wide`, `lead-tall`, or `lead-centred`. |
| `presentation.emphasis` | Optional hint: `one_big_story`, `quiet_day`, or `many_stories`. |
| `presentation.ear_right` | Optional short line for the right masthead ear. |
| `coverage` | Configured feed inventory, check boundary, per-feed outcomes and timestamps, and `complete`, `partial`, or `unknown`; plus an approved reader-facing note. `complete` means all declared configured feeds were successfully checked for that boundary, never complete publisher or historical coverage. Missing evidence requires `unknown`. Render the note and scope explicitly. |
| `inputs[]` | Opaque input bundle IDs and `sha256:` digests, carried into the manifest; never local paths. |

### Field shapes

`contracts/examples/minimal.json` fixes the spelling and nesting of every field; the tables in this
section define meaning. Shapes the tables leave open are settled here:

- `edition.date` is `YYYY-MM-DD` in `edition.timezone`. `timezone` is an IANA name and release 1
  accepts only `Europe/Copenhagen`. `language` is a BCP 47 primary tag and release 1 accepts `en`
  and `da`. `number` is a positive integer.
- `presentation` is optional as a whole, and each of `preferred_composition`, `emphasis`, and
  `ear_right` is optional inside it.
- `coverage` is `{status, checked_from, checked_until, feeds[], note}`. `feeds[]` is the declared
  inventory, each `{feed_id, source, outcome, last_checked_at}`, with `outcome` one of `checked`,
  `failed`, `not_checked` and `last_checked_at` null when not checked. `complete` requires every
  feed `checked`; any `failed` or `not_checked` requires `partial`; an empty inventory requires
  `unknown`.
- `inputs[]` items are `{id, sha256}`.
- `sources[]` items are `{source, source_id, input_id, original_title, url, published_at,
  content_hash, primary}`.
- `limitations[]` values are `digest_of_rss_description`, `translated_from_source_language`,
  `headline_only`, and `partial_source_coverage`. Adding a value is a schema version change.
- `copy.body` keys are exactly `extended`, `standard`, `short`. A `callouts[]` item carries `kind`
  plus the fields of the callout table below and nothing else.
- **Attribution is data, not prose.** A paragraph and a lede are `{text, sources[]}`, where
  `sources[]` lists publisher ids that each name an entry in the story's `sources[]`. Block 3
  renders them as a trailing small-caps marker after the text, linking on the web to that
  publisher's article for the story and unlinked on the device. Copy therefore does not open with
  "X reports that"; a publisher is named in the sentence only when the point is that publishers
  differ. A sourced story cites at least one publisher per paragraph; a story with no sources cites
  none.

### Stories

`stories[]` is ordered and authoritative. Block 3 never re-orders it.

| Field | Meaning |
|---|---|
| `id` | Unique durable editorial story identity. Array position is the sole ordering authority; there is no separate `order` field. |
| `device_participation` | Exactly one of `required`, `optional`, `reserve`. Required stories must fit; optional stories start on the device and may be omitted; reserves are tried afterward. All three are accepted web stories. |
| `kicker`, `kicker_secondary` | The small-caps label above the headline, and an optional second term. |
| `role` | `lead`, `secondary`, or `brief`. **Exactly one `lead` per edition**, always on the device page. |
| `fallback_role` | Optional demotion target. `lead` has no fallback. |
| `copy.headline`, `copy.headline_short` | The headline and an approved shorter form for a narrow slot. |
| `copy.deck` | Optional italic standfirst. |
| `copy.lede` | One attributed sentence, `{text, sources[]}`, shown under a brief's headline. Required when `role` or `fallback_role` is `brief`; ignored in other roles. |
| `copy.body` | Object keyed `extended`, `standard`, `short`, each an array of attributed paragraphs `{text, sources[]}`. All optional; a title-only item supplies none. Approved variants, not budgets block 3 may trim. |
| `callouts[]` | Zero or more candidates in priority order. |
| `sources[]` | Every contributing article: `source` and `source_id` exactly as in block 1, `input_id` referencing `inputs[]`, original title, validated original reading URL, published time, content hash, and one flagged `primary`. Display names come from title config, never a redundant model-authored publisher field. |
| `limitations[]` | Evidence limitations such as `digest_of_rss_description`. |

### Callouts

| `kind` | Required fields |
|---|---|
| `quote` | `text`, `attribution` (the speaker), `attribution_source` (the reporting publisher's id, present in `sources[]`) |
| `figure` | `value` (a short numeral string such as `8.4 bn`), `label` |
| `facts` | `title`, `items[]` of two to four short strings |
| `box` | `label`, `text` |
| `timeline` | `title`, `rows[]` of two to four `{date, text}` |

### Fit policy

`fit_policy` **constrains the device edition only**. The device edition is exactly one page, so
there is no page budget field; multi-page output is designed in the [roadmap](roadmap.md).

| Field | Meaning |
|---|---|
| `allow_role_fallback`, `allow_composition_substitution` | Whether block 3 may demote a role or change composition to make an edition fit. |
| `reserve_story_ids[]` | Every and only `reserve` story ID, once each, in device attempt order. |
| `omittable_story_ids[]` | Every and only `optional` story ID, once each, in device omission order, first to last. Required stories never appear in either list. |

### Validation beyond the schema

Exactly one `lead`, first in `stories[]`, with `device_participation: required` and no fallback.
The only fallback transition is `secondary -> brief`; briefs have no fallback. Every story that can
be a brief carries an approved `copy.lede`. Every cited publisher, including a quote's
`attribution_source`, appears in the story's `sources[]`. Story IDs and input IDs are unique. Policy lists are duplicate-free, disjoint, and equal
to their participation sets. Every nonempty `sources[]` has exactly one primary; all source IDs are
namespaced by publisher, input references exist, publisher mappings are known, and content hashes
have the defined form. URLs must parse as absolute HTTPS URLs without userinfo. No URL is fetched.

Edition IDs, story IDs used as anchors, input IDs, and layout versions match
`[a-z0-9][a-z0-9_-]{0,79}`. Do not apply that grammar to publishers' original `source_id` values.
Validate real calendar dates, supported language/timezone values, and nonempty copy strings and
paragraphs. Limit input JSON to 4 MiB UTF-8 before parsing, stories to 64, sources per story to 16,
input references to 128, callouts per story to 16, and paragraphs per body variant to 64. Strings
are at most 20,000 Unicode code points unless a narrower field bound applies (IDs above, URLs 8,192).
These generous resource bounds are validated by WP 2's corpus; they are not fit budgets.
Coverage sets must match the configured inventory carried in the contract and support their declared
status; block 3 checks consistency, not whether collection really happened. All failures are
`contract_invalid` with the offending JSON pointer in `error.details`.

## 6. What block 3 returns

**`fit-report.json`** records the whole device fit search: every composition considered and why it was
rejected, per-slot measurements, every repair the policy applied in order, every callout dropped, every
story omitted with its reason, and the list of any off-origin request the browser attempted. It is
diagnostic, and it is what block 2's LLM reads to shorten copy.

**`publication-receipt.json`** reports the two outputs separately, because they now differ.

- `web.story_ids[]` — every story published to a reader. **Block 2's repeat-suppression memory updates
  from this set.** A story that reached the website was published whether or not the panel had room.
- `device.status` — `published`, `failed`, or `skipped`.
- `device.story_ids[]`, `device.composition`, and per story
  `{role_as_placed, slot, headline_variant, copy_variant, callout_kind, callout_index}`.
- `device.omitted[]`, `device.dropped_callouts[]`, `device.structural_elements[]`.
- `bundle.path` — relative `n/<edition-id>/`, never a machine path.

The stored receipt describes bundle contents, not proof of activation. Hash it in the manifest, then
return `bundle.manifest_sha256` in the outer CLI result only. The manifest never hashes itself and the
stored receipt never contains its enclosing manifest's digest. `receipt --edition <id>` returns the
stored receipt plus digest and activation evidence only after Section 13 establishes publication.
Block 2 updates memory from this activated result, idempotently by edition ID and manifest digest;
neither a staged receipt nor a successful `fit` is a publication acknowledgment.

**`manifest.json`** identifies the editorial edition, the layout version, the device
profile, the renderer environment (Node, Astro, Playwright, Chromium version and executable digest,
ImageMagick, fonts lock digest), accepted-contract digest, config and layout digests, filenames,
byte counts, and `sha256:`-prefixed hashes. Include shared asset inventories and their hashes, so
verification covers dependencies outside the edition directory. Absent device tools have explicit
null recorded identities and structured failure codes; do not invent versions. Sorted keys,
compact separators, mirroring block 1's `export.py`.

## 7. Compositions and slot capacities

`src/device/catalog/` is the only place capacity is declared.

| Composition | Secondaries | Briefs | Callout slots | Starting variant (lead / secondary) |
|---|---|---|---|---|
| `lead-wide` | 0–3 | 0–4 | lead, any secondary | `standard` / `short` |
| `lead-tall` | 0–3 | 0 | lead, any secondary | `extended` / `standard` |
| `lead-centred` | 0–4 | 0–6 | lead, any secondary | `standard` / `short` |

Every slot declares the copy variant a story starts at, so the body-reduction rung has a defined
origin. Briefs have no body variant; they take the selected headline and `copy.lede`, with visible
publisher attribution. The
values above are the design intent from `design/`; device trials may move them, but they live in the
catalog, never in the fit engine. When a story does not carry the starting variant, it starts at the
longest variant it carries that is not above the starting rung (`extended > standard > short`). If
only higher rungs exist, use the shortest supplied variant and measure it; never silently discard
an approved body. No supplied body means a title-only placement. Variant names establish editorial
preference, not a guarantee of decreasing measured height. Every change is measured.

These are occupancy limits, not minimum density requirements. The original design's preferred counts
(wide: 2–3/3–4; tall: 1–3/0; centred: 3–4/4–6) are visual references. Empty bands and their rules are
removed; remaining whitespace is allowed, without shrinking type or adding filler. A lead alone and
a lead plus one brief must both render. Catalog slot order defines device reading order and must
preserve the relative contract order of placed stories; an incompatible interleaving is a capacity
failure, never permission to group or reorder stories silently.

`one_big_story` prefers `lead-tall`, `quiet_day` prefers `lead-wide`, `many_stories` prefers
`lead-centred`. A composition whose ranges cannot cover the requested counts is rejected
arithmetically, before any render, with count-level repairs specified in Section 10. Adding a fourth composition must not require touching the fit
engine.

**No pixel dimensions in TypeScript.** `device.css` owns every geometry number through custom
properties; the catalog names only slot ids, kinds, selectors, count ranges, and starting variants.
Measurement reads
computed geometry from the DOM, so a design change is a CSS change.

**Provisional type tokens.** Invariant 8 requires one fixed size per role. Until WP 3's physical
trial revises them, `tokens.css` carries the values the mockup uses: masthead 108 px (92 px compact),
lead headline 82 px (72 px in `lead-tall`), deck 36 px italic, secondary headline 44 px, brief
headline 31 px, body 30 px on a 1.42 line height, brief lede 26 px, kicker 23 px and source row
22 px in small caps, quote 38 px (46 px centred), figure 96 px, facts and timeline text 27 px and
26 px. The ranges in `design/README.md` were exploration; the trial picks one number each and the
renderer never varies them by copy length.

## 8. Device rendering: plain templates, not Astro

Astro's Container API was evaluated and **rejected**. It is still exported as `experimental_` and
documented as subject to breaking change even in patch releases; it already moved
`getContainerRenderer()` within the Astro 7 cycle; the docs scope it to testing component output under
Vitest; whether component `<style>` blocks appear in its output is undocumented and unverified; and
`.astro` is not a Node-loadable module format, so any Container design drags a Vite runtime into the
CLI process. Measuring an Astro dev-server route was also rejected: dev mode injects `/@vite/client`,
so the device page would ship a script and open a websocket, violating invariant 2.

Astro's value is entirely in the web path — routing, content collections, permalinks, archive,
prev/next, responsive layout. The device page has one fixed size, three templates, no links, and no
JavaScript. It needs none of that. Under the web-first decoupling the two outputs do not share
coordinates, so the device path loses nothing.

`src/device/render.ts` takes a frozen composition record and returns one complete HTML document string.
`src/device/server.ts` serves it from an in-process loopback server on port 0.

**The shared layer is CSS custom properties, TypeScript types, and string-returning helpers.** Do not
use `<style>` blocks in `.astro` components. At asset-publish time the CLI concatenates
`tokens.css + device.css` and `tokens.css + web.css` into two stylesheets under `a/<layout-version>/`.
Concatenation rather than `@import`, because an `@import` adds a second blocking round trip and a
failure mode to the measurement wait. A newspaper is a design system with a fixed type scale, not a
component-scoped app, so one global stylesheet per output is the right shape and it makes the shared
design language structurally enforced by a single `tokens.css`.

Shared markup helpers in `assets/html/` return escaped HTML strings and are consumed by Astro through
`<Fragment set:html={...} />`. `set:html` does not sanitize, so the escaping discipline in
`assets/html/escape.ts` is the safety boundary and is tested by fuzzing every contract string field.

### Stylesheet invariants the measurement depends on

Every measurable slot must be a hard-bounded box:

```css
.slot { block-size: var(--slot-h); min-block-size: 0; overflow: hidden; }
```

`min-block-size: 0` is load-bearing for grid children, whose default `min-height: auto` lets a child
refuse to shrink and push the track, relocating overflow to the page level where per-slot measurement
becomes meaningless.

Four further rules, which with the bounded-box rule above are the five stylesheet rules Section 17
tests:

- Every text element sets an explicit `line-height`. Computed `line-height` is never `normal`.
- Every multi-column slot sets `column-fill: auto`. The default `balance` with a fixed height still
  overflows sideways, but it changes where text lands, and the probe formula assumes sequential fill.
- `device.css` uses no `:nth-child`, `:first-child`, `:last-child`, `+`, or `~` for layout, because the
  measurement probe clones a slot as a sibling and a clone shifts sibling indices.
- Every device colour token is `#XYXYXY` with `X == Y`, so it lands exactly on a 16-level step.

## 9. Measurement

One `Browser`, one `BrowserContext`, and one `Page` are reused across the whole fit loop. Request
routing disables the HTTP cache; serve local asset bytes from an in-process immutable asset map.
Measure performance with the actual routing policy enabled, not an assumed warm HTTP cache.
[Playwright routing documentation](https://playwright.dev/docs/api/class-browsercontext#browser-context-route).

```ts
const browser = await chromium.launch({ channel: 'chromium', args: [
  '--force-color-profile=srgb', '--font-render-hinting=none',
  '--disable-lcd-text', '--disable-font-subpixel-positioning', '--hide-scrollbars' ] });
const context = await browser.newContext({
  viewport: { width: 1872, height: 1404 }, deviceScaleFactor: 1,
  colorScheme: 'light', forcedColors: 'none', reducedMotion: 'reduce',
  locale: 'da-DK', timezoneId: 'Europe/Copenhagen', serviceWorkers: 'block' });
```

**Network isolation is enforced here**, not by convention. Route every request; continue only loopback
on the server's own port; abort everything else with `blockedbyclient` and record it. A non-empty
off-origin list is a `network_access_blocked` error, not a warning, because it means a font or
stylesheet reference leaked. Apply the same isolation to the fresh capture context. Public diagnostics
retain only request category and a digest of the attempted URL, never the URL, credentials, query, or
fragment. Serve only known generated documents and asset-map entries, not arbitrary filesystem paths.

**Settle sequence per candidate.** Navigate with `waitUntil: 'load'`, never `networkidle`. Await
explicit loading of every vendored face with `FontFace.load()` after checking registration, then
`document.fonts.ready`. Iterate `document.fonts` and assert that every required
`(family, weight, style)` is present with `status === 'loaded'`. Do not use `document.fonts.check()`:
it returns true when no registered face matches the query, which is exactly the state after the
stylesheet 404s and no `@font-face` was ever registered, and `fonts.ready` resolves happily when a face
silently failed. Then await two nested
`requestAnimationFrame`s to guarantee a completed layout and paint. A missing face is `font_not_loaded`
with the face list in `error.details`. Loading all declared faces is deliberate: unused faces may
otherwise remain `unloaded` on a valid page. Also check glyph coverage for edition text against the
vendored fonts and reject unsupported glyphs as `font_glyph_missing`; never accept silent system-font
fallback as reproducible rendering. [CSS font loading](https://www.w3.org/TR/css3-fonts/#font-face-rule).

**Navigate to a distinct URL per candidate**, `/c/<candidate-sha256>/page.html` with `Cache-Control:
no-store`; assets at `/a/<layout-version>/**` with a long immutable max-age. A full document load resets
DOM, styles, and scroll, so nothing else needs resetting between candidates. Do not use
`page.setContent()`: relative URLs then resolve against `about:blank` and the CSS and fonts silently
404, which produces plausible-looking but wrong measurements.

### Overflow detection

The reliable test differs by slot kind, and this is the part most easily got wrong.

| Slot kind | Test | Why |
|---|---|---|
| Block flow (grid child) | Check both `scrollHeight > clientHeight` and `scrollWidth > clientWidth` | Long unbreakable text can clip horizontally as well as vertically |
| CSS multi-column | Check both axes, especially `scrollWidth > clientWidth` | Constrained-height overflow can create extra columns in the inline direction |

Comparing the last child's bottom edge against the container's content box is **not** reliable and must
not be used: it misses content overflowing past the last child, it is fooled by collapsed margins, and
in multi-column the last child sits in the last column so its bottom is inside the box.

**Magnitude comes from a separate off-screen probe.** Clone the slot as a sibling, absolutely
positioned, hidden, unconstrained in height, single-column, and read its natural height. Compute
content-box width and height by subtracting computed padding from `clientWidth` and `clientHeight`;
borders are already excluded. Set the clone's content width explicitly with `box-sizing: content-box`,
remove only its outer constraint/padding/border, and preserve descendant typography and spacing.
For multi-column text the probe width is `(contentWidth − (N−1)·gap) / N` and nominal available height
is `N · contentHeight`. Clear contained floats when measuring natural height. Probe drop caps and
mixed headings/body/source rows in regression fixtures; no single body line-height describes them all.
`overflowPx = natural − available` is an estimate, not a proof of fragmentation fit.

`clipped` is true if an in-place overflow check detects hidden content. A slot fits only when
`!clipped && measuredPx + 3 <= availablePx` and its geometry checks pass. The three-pixel probe margin
is conservative headroom, not proof that fragmented content fits. Integer scroll metrics also require
fractional-boundary fixtures. Actual clipping always rejects the candidate even if the probe reports
slack. Column breaks, widows/orphans, and unbreakable groups can waste column space, so that disagreement
is expected and marked `estimate_reliable: false`, not `measurement_inconsistent`.
[CSS fragmentation and overflow](https://www.w3.org/TR/css-multicol-1/).

Reserve `measurement_inconsistent` for broken harness assumptions: missing/duplicate slots, non-finite
geometry, or different measurements for an unchanged candidate in the same environment. Check the
page frame and every visible region, including masthead ears, source rows, callouts, and folio, against
their bounds. Check nested constrained boxes and overlap as well as top-level scroll metrics. A page
fits only when all regions pass; the viewport hiding overflow is never evidence of success.

### One round trip

A single `page.evaluate` returns, per slot: `availablePx`, `measuredPx`, `overflowPx`, `lineHeightPx`,
`overflowLines`, `lineCount`, `headlineLines`, `clipped`, `fits`, `charsInBody`, `suggestedMaxChars`,
`overflowAxis`, `estimate_reliable`, and failed region/component IDs. Inside
it: read all in-place metrics, append all probes, force one layout, read all probe heights, remove all
probes.

For a reliable vertical estimate, `overflowLines = ceil(max(0, overflowPx + 3) / lineHeightPx)`.
Report null for unreliable estimates or horizontal overflow; include measured excess width or column
count instead. Count lines by component and column index plus rounded `top`, using text-node ranges
so nested inline elements do not double-count and parallel columns do not collapse into one line.
Body character advice is nullable and only computed for a reliable body-only measurement with a
positive height: `floor(charsInBody × availablePx / measuredPx × 0.97)`. Headline, attribution, and
folio failures name their own field; shortening a body is not advice for an overflowing headline.
Block 2 rewrites, block 3 re-measures; all estimates are advisory.

## 10. The fit policy

Word counts are rejected as a fitting mechanism: Danish compounds, long names, and translated headlines
make them unreliable. Every candidate is measured with the real fonts at the real size.

**Selection order.** Build one stable composition preference list: explicit preferred composition
first, then emphasis mapping, then configured order, removing duplicates. If substitution is disabled,
only the first entry is allowed. Start with required and optional stories; reserves are excluded.
Capacity means both role counts and an order-preserving slot assignment. Assign each role to the next
available matching slot, preserving global story order; reject assignments that cannot do this.

**Count-level repairs precede measurement.** If no allowed composition accepts the current stories,
try authorized `secondary -> brief` fallbacks in reverse contract order, retaining each demotion and
rechecking capacity. If still infeasible, omit optional stories in `omittable_story_ids` order,
rechecking after each omission. Neither step touches a required story's participation or removes the
lead. If counts/order remain impossible, return `composition_unavailable` with requested counts,
remaining story IDs, and catalog rejection reasons; there is no invented overflowing slot.

**The initial measured candidate.** Use the first feasible composition, initialize variants by
Section 7, use the full headline, and attach the first callout where supported. Every callout has a
stable contract-array index in the composition and receipt. Unsupported callouts are recorded as
dropped. Later candidates are not alternative wordings automatically tried in release 1; all appear
on the web, but the device uses only the first or none.

For the first failing region in declared slot/component order, apply the first available repair and
remeasure. For a non-story region, skip story-copy repairs and report its contract/config field.

1. Drop that story's callout.
2. If its headline fails, select `headline_short` when supplied and not yet selected.
3. Step down to the next supplied body variant; do not drop the body, deck, lede, or source row.
4. Apply its permitted fallback role, then run count-level selection if necessary.
5. Try the next allowed, unvisited composition state that accepts current counts and order.
6. Omit the next optional story in authorized order, reselecting from the preference list.
7. Return `fit_failed_required_story` for an unplaceable required story, otherwise
   `fit_failed_layout` for a non-story region. Include the measured field, axes, clipping, and nullable
   advisory overflow lines. A capacity failure retains `composition_unavailable` instead.

**Repairs persist.** Keep each story's selected headline, body rung, fallback role, and dropped
callout across composition changes. A new slot may step a body down only to a supplied lower rung;
it never restores removed copy. This is a greedy, bounded policy, not an exhaustive proof that no
approved arrangement fits. Variant labels need not predict physical height, so measure every state.
Composition changes can reuse a composition after the story set or copy state changes.

**Reserves follow a successful base fit.** Try reserves in their declared attempt order, inserting
each into its contract-order position in the current composition. Try only that reserve's callout
removal, short headline, lower supplied body variants, and authorized fallback. Do not switch
composition or alter already placed stories. Remeasure the whole page after each change. If capacity
or any region fails after these repairs, discard the reserve and stop trying later reserves. Keep the
last fitting base and record every attempt. No callout restoration phase exists in release 1.

Never shrink type, clip a paragraph, or drop an attribution qualifier. Whitespace is acceptable.
The frozen composition records all displayed strings or exact contract references, selected headline
and body variants, callout indices, slot assignments, and the accepted contract/config/asset digests.
`render-device` validates these bindings and policy constraints; an arbitrary composition file cannot
authorize different copy or omission of a required story.

**Bounding.** A visited set hashes canonical candidate state: composition, ordered story-to-slot
assignment, roles, headline/body choices, and callout indices. Search bookkeeping also records phase
and reserve cursor so revisiting a measured state cannot create a transition cycle. Count-level states
and reserve attempts count toward `maxCandidates`, default 40. Exhaustion is `fit_budget_exhausted`
even if a fitting base exists; do not silently claim the search completed. Identical inputs exhaust at
the same state. `maxWallClockMs`, default 60 000, is a separate emergency stop with
`fit_wall_clock_exceeded`. Instrument phase timings privately; deterministic public reports exclude
durations, ports, run IDs, and wall-clock readings. Each transition records
`{candidate, slot, action, before, after, measurement}`, with null slot/measurement before rendering.
Benchmark representative dense fixtures with routing and font loading enabled before setting a
performance expectation; no six-second worst-case promise is made.

## 11. Capture and 16-level conversion

The viewport is already exactly 1872 × 1404 at `deviceScaleFactor: 1`, so a plain viewport screenshot
is exactly the frame. No `fullPage`, no `clip` — clipping adds an offset that can be off by one.

```ts
const buf = await page.screenshot({ type: 'png', animations: 'disabled',
                                    caret: 'hide', scale: 'css' });
```

`scale` is set explicitly even though it is moot at `deviceScaleFactor: 1`, because the Playwright docs
contradict themselves on its default and a default change must not silently double the pixels. Use a
page screenshot, not an element screenshot, which scrolls the element into view first and can shift by
subpixels. `device.css` sets `html, body { margin: 0; overflow: hidden }`, which with `--hide-scrollbars`
removes the only mechanism that could shrink the layout viewport. The device edition is one document
at one URL. Assert the size from the PNG IHDR in
the buffer, not from Playwright: mismatch is `screenshot_size_mismatch`.

For final capture, create a fresh context with identical options and network isolation. Repeat face
loading, settling, and every slot/page check against the frozen composition. Require identical
measurements and no clipping before screenshot; a disagreement is `measurement_inconsistent`.
Only a captured, decoded, converted, and verified image establishes device-artifact success.

Convert the master, feeding the buffer on stdin:

```sh
magick png:- -strip -colorspace Gray -depth 4 \
  -define png:color-type=0 -define png:bit-depth=4 png:-
```

Verified on 8 September 2026 with ImageMagick 7.1.2-31 against `design/preview/device-A.png`: output is
`PNG image data, 1872 x 1404, 4-bit grayscale` with exactly 16 unique levels.

`-depth 4` is a per-pixel depth reduction with round-to-nearest, not a quantization, so **an explicit
`+dither` is a verified no-op** — two runs with and without it are byte-identical. Do not add it as
decoration; instead assert the argv array equals a named constant, so that if anyone ever introduces
`-colors 16`, which does dither, the test forces the conversation. The design palette lands on levels
exactly because every grey is a multiple of 0x11.

**`-strip` is required.** Without it ImageMagick writes `tIME` and three `date:` text chunks and two
runs of the same input differ; with it the chunk set is exactly `IHDR`, `IDAT`, `IEND` and the bytes are
identical. Also set `SOURCE_DATE_EPOCH` in the run environment as defence in depth for other tools.

Keep the full-depth master in `var/runs/<run-id>/` for visual regression. The bundle carries only the
4-bit file.

### Verifying the output

Four assertions, cheapest and most authoritative first.

1. **IHDR bytes**, in plain Node with no dependency: signature, `readUInt32BE(16) === 1872`,
   `readUInt32BE(20) === 1404`, `b[24] === 4` (bit depth), `b[25] === 0` (colour type grayscale).
2. **Chunk walk**: the set is exactly `{IHDR, IDAT, IEND}`. Any `tIME` or `tEXt` means `-strip` was
   dropped.
3. `magick identify -format '%w %h %z %k %[type]'` returns `1872 1404 4 <=16 Grayscale`. `%z` reports
   *stored* depth, so `%z == 4` is a real assertion: an 8-bit file containing only 16 colours still
   reports 8.
4. `magick <file> -format %c histogram:info:-` lists at most 16 levels, each a multiple of 17.

Plus a determinism gate: convert the same master twice and assert identical SHA-256.

## 12. The web edition

Story content is built from the validated contract alone. The web build can run independently with
device status `skipped`. In `publish`, finalize the immutable web page after the device outcome is
known. A fit report is optional diagnostic input, never evidence that an image exists: a device link
requires a verified artifact result bound to the same contract/composition digest and image bytes.
Standalone `build-web` validates those referenced bytes before linking an image. It never claims a
page exists merely because fitting succeeded.

**Routes.** `/` is the latest edition. `/archive/` is the index, newest first. `/n/<id>/` is an
immutable permalink. `/go/<id>/prev/` and `/go/<id>/next/` are shell-owned redirect stubs, using a meta
refresh with a real anchor fallback and no JavaScript, so an archived edition page never has to be
rewritten when a newer edition arrives.

**Content.** Every accepted story at the longest approved body variant, in editorial order. Every
approved callout, including those the panel could not hold. An expandable source list per story with
each contributing article's original title, publisher, and time. The coverage note verbatim. Per-story
anchors. A link to the device image when one exists. Render each story's evidence limitations as
reader-visible labels; RSS-based copy must be labeled as such. Briefs and title-only stories retain
their approved lede when applicable, sources, and limitations even without a body variant.

**Composition.** Two compositions exist and `config/title.yaml` selects one (`web_layout`): `grid`,
the lead beside a rail of secondaries with the rest flowing through three columns, and `sheet`, one
sheet of three columns with the lead's headline spanning them. They share one `Story` component and
one type scale expressed as custom properties; a composition may set those properties and its own
placement rules and nothing else, which is what keeps the second one cheap to carry. `build-web
--layout` previews the other; `publish` reads only the config. Grid is the default as of 14 September
2026.

**Layout.** Its own responsive layout, chosen for a browser. It keeps the design language — masthead,
heavy and hairline rules, small caps, kickers, source rows, the type scale, and the five callout kinds —
and adds the warm paper tone and the single dark-red accent. It reflows to one column on narrow screens,
preserving story order and attribution. Real HTML, semantic headings, working links, selectable text,
visible keyboard focus, `prefers-reduced-motion` respected. No client-side framework, no analytics, no
remote assets.

**Astro configuration**, set explicitly rather than inherited, because v7 changed defaults:

```js
export default defineConfig({
  output: 'static',
  compressHTML: false,        // v7 default is 'jsx', which strips newlines between inline
                              // elements and silently eats spaces in source rows
  build: { format: 'directory', assets: '_astro', inlineStylesheets: 'never' },
  trailingSlash: 'always',
  devToolbar: { enabled: false },
});
```

**Build input.** Each invocation owns `var/runs/<run-id>/build-input/`, output, generated Astro root,
and cache directories. No mutable build path is shared across calls, even with different publish
roots. A fresh editions directory contains only `editions/<id>.json`; `index.json` is the current
live release's index snapshot plus the candidate edition. If no release exists, start with an empty
index. Standalone `build-web` takes an optional explicit validated index snapshot. The content
collection's loader globs the editions directory; a second collection loads
`index.json`. The edition page is built from the first; the archive index, the latest pointer, and every
`go/` stub are built from the second, which is the only way they can know about editions this build did
not render. Both Zod schemas are deliberately permissive, since the CLI already validated the edition
against the contract and wrote the index itself. The CLI then runs `node_modules/.bin/astro build
--root site` as a subprocess; the programmatic build API is experimental and buys nothing here, and
`npx` is never used because it may download. The CLI passes the run's build-input directory as the
absolute `PUBLISHER_BUILD_INPUT` environment variable; `content.config.ts` reads it and fails the
build when it is unset or not a directory, so no default path can ever point at another run. Isolation
between builds follows from unique run directories; no concurrency test is required.

**Edition ordering.** Sort by `(edition.cutoff_at, edition.generated_at, edition.id)` ascending with
bytewise ID ordering; archive display reverses it. Latest is the maximum key, not the last invocation.
A backdated publication adds an archive entry without moving latest backward. Prev/next refer to
neighbors in this order. Boundary stubs show a plain "No previous/next edition" page with archive
link and no redirect; later release shells can replace that stub without editing the edition.
If `/` renders an older latest edition during backdated publication, take its HTML from the immutable
store rather than rebuilding it; edition-page links are root-relative so this alias works.

**Output is split.** Astro emits one `dist/`, and the CLI sorts it into the two layers of Section 13:
`n/<id>/**` goes into the edition's bundle in the store, and everything else, the front page, the archive,
the `go/` stubs, and `latest.json`, goes into the release shell. Nothing under `n/<id>/` for an older
edition is ever emitted, because the older editions are not in the editions collection.

**Assets live outside the edition directory**, at `a/<layout-version>/`, referenced by absolute URL.
Letting Astro hash fonts into `_astro/` per edition would carry roughly 200 KB of fonts into every
edition, about 73 MB a year, and would break the guarantee that an archived page renders in 2027 exactly
as it did in 2026. A new layout version writes a new immutable asset directory; old editions keep
pointing at the assets they were published with.

Write the Content-Security-Policy meta tag by hand in the layout rather than using Astro's `security.csp`:
every resource here is first-party and unprocessed, so a hand-written tag is simpler and fully under
control. `default-src 'none'; style-src 'self'; font-src 'self'; img-src 'self'; base-uri 'none';
form-action 'none'`. Anchors to publishers are unaffected.

## 13. Bundle, store, and atomic publication

Editions are neither rebuilt on every run nor copied forward. Each is published once as its own
immutable directory, and only a small mutable shell is rebuilt.

```text
<publish-root>/
  store/
    n/<edition-id>/          immutable, mode 0444, published by ONE rename from .staging-*
      edition.json  fit-report.json  publication-receipt.json  manifest.json
      composition.json       absent when the device build failed
      index.html
      device/page-1.html     the exact HTML that produced the PNG, auditable
      device/page-1.png      absent when the device build failed; numbered so a second page is additive
    a/<layout-version>/      immutable shared assets, published by ONE rename
      device.css  web.css  fonts/*.woff2  OFL.txt
  state/                      private; never part of the docroot
    pending.json              one durable activation intent, or absent
    activations/<run-id>.json retained committed activation records
  releases/<run-id>/         the complete docroot for this run
    index.html  archive/  go/<id>/{prev,next}/  latest.json  index.json
    n/<id>/…                 HARDLINKS into store/n/<id>/
    a/<v>/…                  HARDLINKS into store/a/<v>/
    device/current.png       HARDLINK to the greatest ordering key with a verified device page
  live -> releases/<run-id>  symlink; the docroot
```

Rebuilding all editions each run would replace archived files whenever the layout changed or Astro was
upgraded, invalidating every per-file hash recorded in every old manifest. That is the reason to reject
it, not build time.

**Two different atomic primitives, and the plan must not blur them.** A per-edition directory is
published by one `rename` into a path that does not exist, exactly as block 1's `export.py` does. The
mutable docroot is swapped by renaming a **symlink**, because `rename()` cannot replace a non-empty
directory. Use `fs.link()` per file rather than copying: portable, O(1), and it guarantees byte identity
between store and release. Store files are mode 0444 so an accidental edit cannot mutate the store
through a link; directories retain traversal permission (0555 when finalized). Permissions are an
accidental-write guard, not protection against their owner. Shell-generated files are separate mode
0444 files; only edition and asset files, latest HTML aliases, and device aliases are hardlinks.

### Publication state and recovery

**Stored is not activated.** The linearization point for reader-visible publication is the `live`
symlink rename. A receipt is acknowledged only after the rename and its parent-directory fsync and
the durable activation record succeed. Losing stdout does not undo publication. The current release
contains the authoritative index snapshot; there is no independently updated `store/index.json`.
Committed activation records survive release retention and allow historical receipt lookup.

Under the publish-root lock, execute this protocol:

1. Refuse a new publication while an unresolved intent exists, returning `recovery_required`.
   Validate input/config, path containment, and existing targets. An already activated edition ID is
   `bundle_exists`; a different contract digest at an existing ID is `publish_conflict`.
2. Build and verify the entire candidate in unique staging directories on the publish filesystem:
   new immutable assets if needed, bundle, and complete release shell/index. Hardlink candidate
   edition/asset files into the staged release; inode links survive subsequent directory renames.
   Include all existing archive editions and asset versions. Freeze the prior live target, target
   run ID, contract digest, manifest digest, shared-asset digests, and staged/final paths in an intent.
3. Fsync every staged file and directory. Atomically write/fsync `state/pending.json` and its parent
   before promoting anything. Its paths are private, root-relative, validated, and owned by this run.
4. Rename each new asset directory and edition directory to its final immutable path, fsyncing source
   and destination parents. Rename the complete staged release into `releases/<run-id>/` and fsync
   its parents. Existing equal asset versions are reused; differing bytes are `asset_version_conflict`.
5. Confirm `live` still matches the recorded predecessor (or is absent on first publication), then
   rename a temporary relative symlink over `live` and fsync the publish root. A mismatch is
   `publish_conflict`, never permission to overwrite an unexpected live release.
6. Atomically write/fsync `state/activations/<run-id>.json`, with predecessor, edition and manifest
   identity, index digest, and activation metadata. Remove the pending intent and fsync `state/`.
   Return the activated receipt and digest. Only then perform best-effort release retention.

`recover` takes the same lock. It verifies the intent and every retained/staged object against their
recorded hashes, then finishes missing promotions and activation without rerendering. A promoted target
matching the intent is reused; a retained activation record matching that intent is not rewritten.
If `live`
already names the target, it only completes the durable acknowledgment. If `live` is the predecessor,
it completes the planned swap. Any other target or hash mismatch stops with `publish_conflict` or
`bundle_integrity_failed`, preserving evidence. Recovery is idempotent, never an edition revision and
never an overwrite of different bytes. No pending intent means a successful no-op.

Before an intent is durable, failures leave only run-owned staging, which can be cleaned. After it
is durable, preserve all recovery material until activation finishes. Crash tests cover the three
boundaries named in WP 5; the protocol is designed so every other interruption reduces to one of them.
An activated-but-unacknowledged result is `publication_outcome_uncertain`, with `recover`/`receipt`
instructions, not a claim that nothing published. Ordinary post-commit retention/logging failures are
warnings on success. Recovery material and activation records are never swept as stale run files.

`receipt --edition <id>` is read-only and requires retained activation evidence for that edition and
manifest. A pending activation returns `recovery_required`, a stored-only edition returns
`edition_not_activated`, and an unknown ID returns `resource_not_found`. After recovery, block 2 can
retrieve the result and update memory once even if the original command's stdout was lost. Release
records indicate local activation, not hosting, delivery, or reader access.

### Device failure policy

Partial success is allowed only when the web build and publication integrity checks succeed.

| Failure class | Default `publish` | `--require-device` |
|---|---|---|
| Capacity/search: `composition_unavailable`, `fit_failed_required_story`, `fit_failed_layout`, `fit_budget_exhausted` | Web publishes, device failed, exit 0/partial; preserve exact cause | No activation, exit 1 with original cause |
| Device availability: missing device-only dependency, `renderer_unavailable`, `font_not_loaded`, `font_glyph_missing`, `render_timeout`, `fit_wall_clock_exceeded`, `quantize_failed` | Web publishes only if independently valid, device failed, exit 0/partial; operator-directed cause | No activation, exit 1 with original cause |
| Integrity/isolation: `measurement_inconsistent`, `screenshot_size_mismatch`, `image_invariant_violation`, `network_access_blocked`, hash/config/path conflict | Stop before activation, exit 1 with original cause | Same |
| Web build, common dependency, or contract failure | Stop before activation, exit 1 | Same |

`--skip-device` explicitly publishes web-only with `device.status: skipped`; it conflicts with
`--require-device`. Before device packages exist, the web milestone uses this flag. Never advertise a
PNG from a fitting report alone. A missing shared font that invalidates the web output is a web
failure, not a reason to bypass web validation.

For failed/skipped device output, exclude composition and device files from the public bundle and
keep diagnostic partial artifacts private. Do not change `device/current.png`; retain the prior
hardlink bytes and mtime, or omit the route if no device edition has ever succeeded. `latest.json`
records separate web and device edition IDs (device nullable), dates, and statuses so an old image is
never labeled as today's. A successful backdated device build advances current only if its ordering
key is greater. Latest metadata describes those selected editions, not automatically the current
invocation; its publication result separately describes the candidate edition. Hosted conditional
responses are outside release 1; WP 14 tests the local adapter.

**The bundle contains no machine-specific data.** The manifest records versions and content hashes,
never absolute paths: the Chromium executable is identified by `browser.version()` and the SHA-256 of
the executable file, the store by nothing at all. The machine-specific facts, executable path, publish
root, hostname, go to `var/runs/<run-id>/run.json`, which is never linked into a release. Public
documents use explicit schema allowlists; reject unknown fields rather than copying diagnostics or
input objects wholesale. No private evidence passages, prompts, model logs, local paths, or raw
attempted network URLs reach a release. A path-string scan supplements schema validation; it does not
replace it. Resolve all writes under the configured runtime/publish roots, reject symlink escapes and
unsafe path components, and never delete a path merely because its name resembles staging.

**One lock.** `publish` and `recover` take `<publish-root>/.lock` with an exclusive create for the whole run and
removes it on exit. A held lock is `lock_busy` immediately; the second run never waits, because two
overlapping cron runs should surface as an error rather than queue. A stale lock older than an hour is
reported as `lock_busy` with the lock's age in `error.details`, never removed automatically. Document
manual recovery: establish that the owning process is gone, remove only the confirmed stale lock,
then run `recover --dry-run` and `recover`. Dry-run publish/recover take the same lock to read a stable
snapshot. Other mutating actions use isolated run directories and exclusive non-overwriting output
publication; they never touch this store. No global shared Astro build directories are permitted.

**Retention.** After the symlink swap, delete every `releases/<run-id>/` older than the newest five,
never the one `live` points at or any pending activation target. Order committed releases by durable
activation sequence, not filesystem mtime. Releases are hard links, so deletion frees only the shell;
the store and activation records are untouched. The count is configurable (minimum one), and deletion
is logged per directory. Failures are success-envelope warnings and can be retried on the next run.

**Store and releases share one filesystem.** `fs.link()` fails across filesystems. At startup, `publish`
creates a temporary file under `store/` and links it under `releases/`; failure is
`publish_root_invalid` before durable publication changes. Staging for every rename also resides on
that filesystem. A dry run removes the temporary probe. Fsync support and atomic rename behavior are
part of the supported local-filesystem prerequisite.

## 14. Reproducibility, security, and configuration

**Pinning.** Exact versions, no ranges. `engines: { node: ">=26.0.0 <27" }`, `packageManager`, an
`.nvmrc`, and an `overrides` entry pinning `playwright-core` to the same version as `playwright`,
because the browser revision is tied to `playwright-core` and a transitive dependency could otherwise
change the renderer silently. Install only with `npm ci`.

Install the browser hermetically: `PLAYWRIGHT_BROWSERS_PATH=0 node_modules/.bin/playwright install
--no-shell chromium`. That places it under `node_modules/playwright-core/.local-browsers`, so another project
running `npx playwright install` cannot move this renderer. Record `browser.version()` and the SHA-256
of the executable in the manifest, and the executable path only in the private run record.
`verify` checks archived bytes, schemas, required assets, and internal references without launching
the original renderer. `doctor --compare <manifest>` separately reports environment differences and
the need for visual regression before producing new editions. An upgrade never invalidates intact
archive bytes merely because the current browser differs.

**Fonts.** Two families, settled 11 September 2026 after a specimen review: Newsreader for
everything read (masthead, headlines, decks, body, quotes, figures) and Libre Franklin for
everything small (kickers, datelines, source rows, citation markers, navigation, folio). This is
the Times' system in open-licensed faces: a news serif with optical sizes and a Franklin Gothic
revival for labels. Vendor four variable WOFF2 files of the Google Fonts `latin` subset (Newsreader
weight 200–800 with optical size 6–72, upright and italic; Libre Franklin weight 100–900, upright
and italic) with `OFL.txt` and a `fonts.lock.json` recording each file's SHA-256, byte count, and
exact upstream package path. Variable files are the deliberate exception to the static-instance
preference: Newsreader's value is its optical-size axis, and a single pinned Chromium renders one
variable file as reproducibly as an instance. The `latin` subset, not `latin-ext`, is load-bearing:
`latin-ext` alone lacks ASCII and æøå and falls back silently to a system serif. Do not use Astro's
Fonts API: it emits hashed filenames, which breaks the stable asset path, and generates metric
fallbacks, which is the wrong behavior in a system where a missing font must be a hard error. Two
gates: every file's hash matches the lock, and every family used in the stylesheets has a
matching `@font-face` and appears in the measurement code's required-face list. Labels are Franklin
capitals with tracking, never synthesised small caps. Record any typography change from the
physical trial and refresh references before treating screenshots as golden baselines.

**Freeze display formatting.** Format date/time metadata in Node once using the contract's validated
language and timezone; retain those strings in both web render input and frozen device composition.
Do not reformat approved copy such as figure values. Record Node/ICU identity and title-config digest:
Node formatting can change with an upgrade even though replay from frozen strings remains stable.
Set `TZ` and context locale/timezone explicitly and inject clocks; one fixture crosses a Copenhagen
DST boundary.

**Hyphenation is decided at build time.** Body copy and ledes receive discretionary soft hyphens from
TeX patterns for the edition's language (British English and Danish) with limits and an exception list in
`config/hyphenation.json`; stylesheets set `hyphens: manual`, so every reader's browser and the pinned
device Chromium break words at the same points, and a missing OS dictionary changes nothing. Soft hyphens
are presentation: `edition.json` and the contract digest never contain one.

**Animations are disabled three ways**: `reducedMotion: 'reduce'` on the context, `animations:
'disabled'` on the screenshot, and `*, *::before, *::after { animation: none !important; transition:
none !important }` in `device.css`.

**Build determinism** is asserted, not assumed: build twice from the same input and compare file hashes.
Rolldown and Vite 8 chunk hashing should be deterministic but carries no documented guarantee, and the
gate also catches an accidental `Date.now()` in a template. Parse HTML and CSS resource references,
including `srcset`, `url()`, imports, scripts, and inline event handlers, and exercise the web output
under the same off-origin request block. Remote HTTPS publisher navigation anchors are allowed;
remote resource loads and protocol-relative URLs are not. Text containing a URL is not a resource
request. CSP and DOM-injection tests complement this audit rather than replacing it.

**Configuration.** `config/title.yaml` holds what belongs to the publication rather than to a day: the
title id, masthead wording, device profile dimensions, default composition preference order, and the
publisher-id to display-name mapping. Block 2 supplies the day; block 3 supplies the title's identity.
Display only publishers that actually contributed to the edition.

There is one title. The store and release layout in Section 13 is authoritative and carries no title
prefix; one archive, one latest pointer, one device pointer. Multiple titles are designed in the
[roadmap](roadmap.md).

Reproducibility means the same composition and pinned environment yield stable artifacts. It does not
promise byte-identical PNGs across operating systems or browser upgrades.

## 15. CLI contract

One POSIX `sh` wrapper, `publish_news.sh`, self-locating, emitting a `dependency_missing` envelope when
`node_modules` is absent and otherwise execing `bin/publish_news.ts`. Node runs TypeScript directly, so
there is no build step for the CLI; `tsc --noEmit` is the typecheck gate. It is the only entry point;
do not invoke `npm`, `node`, or `astro` directly for routine work. Operator provisioning in Section 16
is the explicit exception. The wrapper uses installed binaries only and never installs dependencies.

Stdout is exactly one compact key-sorted JSON object per invocation, matching block 1's shape:

```json
{"ok":true,"action":"publish","result":{},"meta":{"cli_version":"0.1.0","envelope_version":"1.0"}}
```

`meta.envelope_version` versions the envelope shape. It is deliberately not called `schema_version`,
which is the contract's field and means something else.

Exit `0` on success, `1` on a well-formed action that failed, `2` on a usage error.

| Action | Mutates | Purpose |
|---|---|---|
| `list-actions` | no | Sorted, self-describing catalog for an LLM caller |
| `schema` | no | Return a named/versioned contract and digest inside the JSON envelope |
| `validate` | no | Schema and invariant check on an edition file |
| `fit` | no | Run the measured fit loop and emit the fit report; write no artifacts |
| `render-device` | yes | Capture and convert from a frozen composition |
| `build-web` | yes | Build from a contract, optional index snapshot, and optional verified device artifact result |
| `publish` | yes | Full pipeline into the store and a new release |
| `recover` | yes | Complete a durable pending activation without rerendering; supports `--dry-run` |
| `receipt` | no | Look up an activated edition receipt and manifest digest after a lost response |
| `verify` | no | Re-check every hash and invariant in a published bundle |
| `doctor` | no | Pinning report; optional `--compare <manifest>` reports renderer differences separately from archive integrity |
| `check` | temporary work only | Offline lint, types, tests, and wrapper syntax through installed tools |
| `version` | no | CLI and schema versions |

`fit` is the action block 2's LLM calls in a loop. It is read-only, needs no output directory, and its
report names the slot, story/field, clipping axes, and advisory nullable overflow in lines. Browser
profiles may use automatically cleaned temporary storage; read-only means no publication-state or
retained-artifact writes. `doctor` is a private diagnostic report, not a public bundle file.

Stable snake_case error types: `usage_error`, `contract_invalid`,
`contract_unsupported_schema_version`, `composition_unavailable`, `fit_failed_required_story`, `fit_failed_layout`,
`fit_budget_exhausted`, `fit_wall_clock_exceeded`, `measurement_inconsistent`, `font_not_loaded`, `render_timeout`,
`screenshot_size_mismatch`, `quantize_failed`, `image_invariant_violation`, `network_access_blocked`,
`web_build_failed`, `asset_version_conflict`, `bundle_exists`, `publish_conflict`, `lock_busy`,
`publish_root_invalid`,
`renderer_unavailable`, `dependency_missing`, `font_glyph_missing`, `recovery_required`,
`publication_outcome_uncertain`, `edition_not_activated`, `resource_not_found`, `bundle_integrity_failed`,
`check_failed`.

`--dry-run` on `publish` validates and renders the candidate in isolated staging, including release
assembly, and returns planned hashes and target pointers. It writes no durable intent, activation
record, final store directory, release, or live pointer. Its result is explicitly planned, never an
activated receipt. `recover --dry-run` verifies retained intent/files and reports missing transitions
without advancing them. `render-device --dry-run` and `build-web --dry-run` produce and verify the same
temporary outputs as real execution but never rename them to the requested destination. Clean only
temporary files created by that invocation; no dry run performs retention or repairs previous runs.

## 16. Work packages and completion gates

**Provisioning prerequisite.** Node 26.5.0, npm 11.17.0, and ImageMagick 7.1.2-31 were verified on
the development machine on 11 September 2026 (macOS, APFS). Initial lock creation and browser
installation are explicit operator setup, not behavior of `check` or `publish`. Document exact setup
commands and versions in publisher operations documentation. The operator installs the pinned
browser after WP 1 creates the lock and before batch 3 starts.

Execution is three handoff batches. Each ends in an owner review of the artifacts that become
contracts, and no batch starts before the previous one is reviewed.

1. **WP 1 and WP 2.** Skeleton and the contract schema. Review the schema and golden documents.
2. **WP 3, WP 4, WP 5.** The web edition and the recoverable store, published with `--skip-device`.
   This is a complete, shippable web product.
3. **WP 0, then WP 6–10.** Measured device output. Review WP 0's findings before WP 7 starts; they
   decide the probe design.

WP 11–13 complete release-1 validation. WP 14 is an optional post-release local adapter, not a
release gate or authorization to host anything.

**WP 0 — Retained rendering experiments (start of batch 3).** Answer Section 20 questions 1 and 2
through the wrapper against pinned Chromium with routing enabled. Test constrained multi-column
overflow, column breaks leaving slack, fractional edges, horizontal block overflow, and drop caps;
compare actual clipping to the advisory probe. Capture five repeated screenshots with the three
font-rendering flags together and five without; keep the set only if it improves repeatability
without visible quality loss. Do not test flags individually. *Complete when*
results, environment, and date are recorded, useful cases remain in `tests/fixtures/`, and the
experiments can be rerun through `check`. Do not label unrun assumptions as measured facts.

**WP 1 — Skeleton, CLI envelope, and `doctor`.** `publish_news.sh`, `package.json` with exact pins and
the `playwright-core` override, `tsconfig.json` with `erasableSyntaxOnly`, `allowImportingTsExtensions`, and
`noEmit`, `bin/publish_news.ts`, the
action catalog, envelope, exit codes, and error types. Implement `list-actions`, `version`, `doctor`,
and `check` with lint, `tsc --noEmit`, tests, and `sh -n`, capturing bounded subprocess output tails.
*Complete when* the wrapper runs from outside the repository, `list-actions` is sorted and
self-describing, a usage error exits 2 with a JSON envelope, stdout is a single object in every case,
and a clean provisioned clone passes the offline check and reports the recorded dependency identities.
Absolute install paths may differ; dependency versions/digests must not. Setup, including the pinned
browser installation, is separate from the wrapper's network-free verification.

**WP 2 — Contract schema and validation.** Section 5 as hand-written JSON Schema in `contracts/`, the
golden documents in `contracts/examples/`, generated TypeScript types, an Ajv validator, and the
`schema` and `validate` actions. *Complete when* every golden document and every fixture validates,
unknown fields are rejected, each Section 5 invariant is rejected with `contract_invalid` naming the
JSON pointer to the offending value, an unsupported `schema_version` is rejected distinctly, and the
generated types compile against every golden document without a cast. The rejection corpus is
table-driven: one document per Section 5 invariant and no more. Add the independently versioned
receipt, manifest, frozen-composition, device-artifact-result, and fit-report schemas, each with one
accepted example.

**WP 3 — Design layer and fonts.** Vendored WOFF2 faces with `OFL.txt` and `fonts.lock.json`,
`tokens.css`, `device.css`, `web.css`, and the escaping and markup helpers, ported from
`design/device.html`. *Complete when* every font hash matches the lock, every `(family, weight, style)`
in the stylesheets has an `@font-face`, explicit loads work even for unused faces, and every device
colour token is `#XYXYXY` with `X == Y`. One escaping test injects a fixed string containing
`<script>`, `&`, `"`, `'`, and `</div>` into every allowed text field of one fixture and asserts the
rendered DOM recovers the exact text with no added element or attribute. No fuzzing.

Use a typography sheet and one provisional composition for an early physical-device trial. The user
loads the image manually by the same method as WP 12; no upload/account automation is authorized.
Check body, briefs, attribution, rules, and all callout kinds at arm's length. Record chosen sizes
and fonts before freezing all three compositions and visual baselines. If hardware is unavailable,
web/store work can continue, but device typography cannot be declared physically validated.

**WP 4 — Web edition.** Section 12: Astro config set explicitly, content collection, layouts,
components, routes, redirect stubs, coverage note, archive index, latest pointer. *Complete when* a
fixture builds to a site containing every story and callout at full length, links resolve, the page
reflows to one column at 400 px, the CSP meta tag is present, parsed resource references satisfy
Section 14's policy (HTTPS publisher anchors remain allowed), and two builds from the same input produce
identical file hashes. Also test one backdated edition and the first/last navigation stubs. No
concurrency test.

**WP 5 — Store and release.** Section 13: staging, hashing, sorted-key manifest, per-edition rename,
hardlinked releases, durable intent/activation records, symlink swap, `recover`, `receipt`, `verify`,
and `build-web`/`publish` with dry runs. *Complete when* three crash injections pass: before the intent is
durable (only staging exists and `recover` is a no-op), after the intent and before the `live` swap
(`recover` completes the swap), and after the swap and before the activation record (`recover`
completes the acknowledgment). Also assert `bundle_exists` on a repeated id, `publish_conflict` on
differing bytes, `lock_busy` on a held lock, a first publication, one backdated publication, receipt
lookup after a simulated lost response, and that `publish --dry-run` leaves the publish root
byte-identical. Hardlinks and file modes are checked once, in the first-publication test.

**WP 6 — Device compositions.** `catalog/`, `render.ts`, `server.ts`, and the three compositions behind
a fixed 1872 × 1404 frame with no links and no scripts. *Complete when* each renders from a fixture at
exactly the target size, matches the corresponding image in `design/preview/` on visual inspection, and
the rendered HTML contains no `<script`. Include lead-only, lead-plus-one-brief, every permitted
occupancy boundary, and interleaved role order; incompatible order is reported, never silently changed.

**WP 7 — Measurement harness.** Section 9: browser lifecycle, loopback server, route blocking, font
assertion, settle sequence, and the single-evaluate probe. *Complete when* the five stylesheet rules
of Section 8 hold (computed `overflow` hidden on both axes and `min-block-size` 0 on every slot, no
computed `line-height` of `normal`, no structural selectors, `column-fill: auto`, greys on 16-level
steps), every clipped region fails regardless of probe estimate, a slot with two pixels of probe slack
reports `clipped: false, fits: false`, and one dense fixture measures identically twice. Both overflow
axes and one multi-column fragmentation case are covered by WP 0's retained fixtures.

**WP 8 — Fit policy.** Section 10: the bounded state machine, the visited set, the budgets, the trace,
and the `fit` action. *Complete when* each rung of the ladder is exercised by its own fixture, the trace
records every transition in order, budget exhaustion is reachable and reported as
`fit_budget_exhausted`, and the required-overflow fixture fails with `fit_failed_required_story` carrying
the slot and advisory overflow in lines. One fixture per rung is the whole test; do not add fixtures
for combinations of rungs.

**WP 9 — Capture and conversion.** Section 11. *Complete when* the PNG buffer's IHDR is 1872 × 1404 at
bit depth 4 and colour type 0, the chunk set is exactly `{IHDR, IDAT, IEND}`, `identify` returns
`1872 1404 4 <=16 Grayscale`, every histogram level is a multiple of 17, two consecutive captures of one
frozen composition are byte-identical, and two conversions of one master are byte-identical. Assert
that the fresh capture context repeats the full measurement and network-isolation checks; no PNG
is accepted on dimensions alone.

**WP 10 — Device failure path.** Wire `device.status` through the receipt, the manifest, and the web
template. *Complete when* an edition that cannot fit publishes the web bundle with
`device.status: "failed"`, `device/current.png` still resolves to the previous edition with unchanged
bytes and mtime, the web page renders no device affordance, `publish` exits 0 with
`result.status: "partial"`, and `--require-device` instead activates nothing and exits 1 with the
original cause. Exercise one failure from each row of Section 13's table plus a skipped device on
first publication. The web template links an image only when its verified artifact result matches
actual bytes.

**WP 11 — Failure and operations review.** Complete Section 17 through the `check` entrypoint created
in WP 1. Document provisioning, stale-lock handling, recovery, lost-response receipt reconciliation,
dry-run semantics, retention warnings, and archive verification versus renderer comparison.
*Complete when* a clean provisioned checkout passes with no network access, archive verification
survives a changed current renderer, and recovery/receipt CLI smokes pass in temporary publish roots.

**WP 12 — First-edition validation.** Build one real edition from a hand-written contract based on
actual block 1 output. Compare against `design/preview/` at the physical device size, then load the PNG
on the TRMNL X by hand: the user places `page-1.png` at a URL they control and enters it into the Image
Display plugin themselves. Block 3 does not upload, configure, or call anything. *Complete when* the
panel shows a legible page, every callout kind survives
quantization, and the receipt describes exactly what was published.

**WP 13 — Variation review.** Generate seven consecutive editions spanning dense, sparse, long-headline,
Danish-text, missing-description, and partial-coverage cases. *Complete when* they differ in
composition, role counts, and callouts while type sizes, margins, rules, and palette are identical
across all seven.

**WP 14 — Post-release local delivery adapter (optional).** A thin adapter around page URLs and publication status, and a
local server serving the current page with `ETag` and `Last-Modified` validators that change with the
image bytes. No hosting, no account configuration. *Complete when* a conditional request for an
unchanged page returns 304 and a new edition with different image bytes returns 200 with new
validators. Use a content-digest ETag, retain mtime when bytes are unchanged, and test conditional
request precedence and absent-current-image behavior. This is a local fixture server, not hosting.

## 17. Test and fixture policy

Tests exist to hold the invariants in Section 1 and the contracts in Sections 5, 6, and 15. A test
that guards no invariant and no contract is not written. Every default test is network-free and uses
temporary directories. `contracts/examples/` holds the only edition documents; `tests/fixtures/`
holds CSS cases, WP 0's retained measurement cases, crash scripts, and reference PNGs.

The eight edition documents are `minimal`, `dense`, `sparse`, `long-headline`, `danish`,
`all-callout-kinds`, `required-overflow`, and `partial-coverage`. They are why block 3 is buildable
and testable before block 2 exists.

| Area | Tested | Deliberately not tested |
|---|---|---|
| Contract | Every golden document accepts; one rejection document per Section 5 invariant, asserting code and JSON pointer | A Python validator; generated inputs |
| Escaping | One fixed injection string through every text field, DOM text recovered exactly | Fuzzing |
| CSS invariants | The five rules of Section 8, by reading the stylesheet | Anything visual |
| Measurement | Clipped always fails; two-pixel slack fails; one dense fixture measures identically twice; WP 0's retained cases | Geometry matrices |
| Fit | One fixture per ladder rung, asserting on the recorded trace | Combinations of rungs |
| Image | IHDR bytes, chunk set, `identify` output, histogram levels; two captures and two conversions byte-identical | Cross-machine identity |
| Web | Every story and callout present at full length; no remote resource reference; two builds hash-identical; one backdated edition | Concurrent builds; time-zone matrices |
| Publication | The three crash boundaries of WP 5; repeated and conflicting ids; held lock; dry run leaves the root byte-identical; receipt after a lost response | Fsync permutations; retention edge cases; stale-lock ageing |
| Boundary | `device/` and `site/` do not import each other | |
| Smoke | `publish_news.sh publish` from outside the repository, asserting on the envelope and the files on disk | |

Visual regression is a manual step, not a test. Reference PNGs for the three compositions and the
web edition at two widths are checked in, and `doctor --compare` tells the operator to re-inspect them
before publishing after a renderer, font, or Astro change.

Assert structured fields, never human log wording. Freeze or inject clocks; do not sleep.

## 18. Acceptance criteria

1. `publish_news.sh check` passes from a clean provisioned checkout with no network access.
2. `validate` accepts every golden document and rejects every rejection document with
   `contract_invalid` and the offending JSON pointer.
3. `fit` on the same fixture twice returns identical reports; `required-overflow` fails with
   `fit_failed_required_story` naming the slot and the overflow in lines; lead-only and
   lead-plus-one-brief fit.
4. Every device PNG is 1872 × 1404, colour type 0, bit depth 4, at most 16 levels each a multiple of
   17; two captures of one frozen composition and two conversions of one master are byte-identical.
5. Every story and callout in the contract appears in the web edition at full approved length, and
   the page reflows to one column at 400 px with story order and attribution preserved.
6. No generated page references a remote resource; HTTPS publisher anchors remain working links;
   blocked-request failures disclose no raw URL.
7. A device fit failure publishes the web edition, leaves `device/current.png` byte-unchanged, and
   reports `result.status: "partial"`; `--require-device` activates nothing and exits 1 with the cause.
8. Each of WP 5's three crash injections recovers to a coherent release through `recover` without
   rerendering; `receipt` reconciles a lost response so block 2 updates memory once.
9. Publishing an activated edition id fails with `bundle_exists`, differing bytes with
   `publish_conflict`, and neither changes anything. Dry runs leave the publish root byte-identical.
10. `verify` checks bundle and shared-asset hashes without the original renderer installed.
11. The receipt's web story set is a superset of its device story set.
12. Seven consecutive fixture editions differ in composition, role counts, and callouts with
    identical type sizes, margins, rules, and palette, and one real edition is legible on the TRMNL X
    with every callout kind surviving quantization.

## 19. Explicit deferrals

Publisher photography and any remote asset path. A CMS, including Keystatic, which would also need a
version compatible with Astro 7. Paged.js, flowing article text, and PDF output. A portrait device
profile. Hosting, TRMNL account configuration, and any network delivery beyond the local adapter in
WP 14. Human override tooling. Search over the archive. A containerized build, which stays available but
is not built now. Edition revisions and correction notices, multi-page device output, and multiple
titles, whose settled designs are in the [roadmap](roadmap.md).

## 20. Open questions to settle by spike, not by argument

Each of these was researched and left unresolved; each has a work package that answers it empirically.

1. **CSS multi-column overflow reports through `scrollWidth`.** This is what the multi-column spec
   describes, but the actual pinned harness has not been run. WP 0 tests both overflow axes and
   fragmentation slack, padding, floats, and fractional edges before recording measured behavior.
2. **The three Chromium font-rendering flags.** Widely used for screenshot stability but absent from
   Playwright's documentation. WP 0 compares repeatability and visual quality, not merely whether a
   flag changes bytes. Keep only flags with demonstrated benefit.
3. **Rolldown and Vite 8 build determinism.** No documented guarantee was found. WP 4's build-twice gate
   answers it.
4. **`page.screenshot({ scale })` default.** The Playwright docs contradict themselves. Moot at
   `deviceScaleFactor: 1`, and set explicitly regardless.
