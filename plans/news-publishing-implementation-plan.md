# Detailed implementation plan: broadsheet publishing

Status: implementation plan, 8 September 2026. Its architecture companion is
[Block 3: Broadsheet publishing architecture](news-publishing-architecture-plan.md), which is
authoritative on boundaries where this document is silent. The upstream contract is defined in
[Block 2: Newspaper editorial architecture](news-editorial-architecture-plan.md). The visual
direction is in [`design/README.md`](design/README.md).

## 1. How to use this plan

Block 3 turns one accepted edition from block 2 into a newspaper. It is a module an LLM in block 2
calls, so its interface is a JSON-in, JSON-out command, and its failures name the slot that overflowed
and by how much, so block 2 can shorten copy and retry rather than guess.

Implement the work packages in Section 15 in order. Each names the files to create, the behavior to
implement, the tests to add, and the condition that makes it complete. Sections 3–14 are the normative
specification; work packages cross-reference them rather than repeating them.

These invariants outrank any conflicting detail below.

1. Block 3 never calls a language model. It selects among the copy variants block 2 supplied and
   measures boxes. It does not rewrite, shorten, or re-order approved copy, and it never composes
   callout text.
2. The renderer visits no publisher URL, loads no remote font, script, or image, and executes no HTML
   or Markdown emitted by a model. Every contract string is escaped before it reaches a template.
3. The web edition is the product. It carries every story and callout the edition accepted, at full
   approved length. Only the device edition may omit anything, and nothing in the web edition is
   constrained to keep parity with the panel.
4. A published edition directory is immutable. Corrections create a new revision. A design change or a
   renderer upgrade never rewrites an archived edition's files.
5. Device pages are exactly 1872 × 1404 pixels, PNG colour type 0 at bit depth 4, at most 16 distinct
   grey levels, never dithered.
6. Stdout is one compact key-sorted JSON object per invocation. Diagnostics go to stderr.
7. Every mutating action supports `--dry-run` and performs full validation before any write.
8. Type sizes, margins, rule weights, and the palette are fixed. Only composition, role counts,
   callouts, and structural elements vary between editions, and they vary from editorial signals.

The first release ends when Work Package 12 passes and one real edition has been read on the device.

## 2. Product boundary

**In scope.** Validating an edition contract; building the web edition with per-edition permalinks, an
archive index, and a latest pointer; choosing a device composition and fitting stories to it by
measurement; capturing the device pages and converting them to 16-level PNG; publishing an immutable
bundle atomically; returning a publication receipt and a fit report to block 2.

**Out of scope for the first release.** Publisher photography, a CMS, Paged.js, PDF output, a portrait
device profile, hosting, TRMNL account configuration, and any network delivery. The delivery adapter is
an interface and a local verification path only. These plans authorize no public posting.

**Repository.** A new repository, `personal-newspaper`. Block 3 occupies `publisher/`. `editorial/` is
reserved for block 2's Python application. Neither block claims the repository root. `news-gatherer` is
unchanged and gains no Node dependency.

## 3. Locked technical decisions

Versions below were checked on 8 September 2026. Do not invent versions in advance; resolve once, pin
exactly, and commit the lockfile.

| Decision | Choice | Evidence |
|---|---|---|
| Web framework | Astro 7.3.1 | Current release; Astro 6 shipped March 2026, Astro 7 on 22 June 2026 |
| Device rendering | **Plain TypeScript templates, no Astro** | Section 8 |
| Runtime | Node 26.5.0, `engines: ">=26 <27"` | Astro 7 requires Node ≥ 22; Node 26 strips TypeScript types natively |
| Browser | Playwright 1.63.0, `channel: 'chromium'` | The default headless shell is a stripped build with a different font stack |
| Contract validation | Hand-written JSON Schema, validated with Ajv | Section 5. TypeScript types are generated from the schema, not the reverse |
| Astro content collection | Zod 4 | Astro 6 upgraded to Zod 4 and dropped Zod 3. Used only for content already validated at the CLI boundary |
| Image conversion | ImageMagick 7.1.2-31 | Verified on this machine |
| Package manager | npm 11.17.0, `npm ci` only, `package-lock.json` committed | — |
| Fonts | Playfair Display and Source Serif 4, OFL, vendored WOFF2 static instances | Section 14 |
| Persistence | None | Block 3 is a function from an edition file to a bundle directory |

Block 3 holds no database. Everything it needs arrives in the edition contract or its own config, and
everything it produces lands in the bundle. That is what makes it safely re-runnable.

## 4. Target repository layout

```text
personal-newspaper/
  README.md
  AGENTS.md
  editorial/                     RESERVED for block 2 (Python). README only for now.
  publisher/
    publish_news.sh              allowlisted entrypoint, mirrors gather_news.sh
    package.json                 one package, no workspaces, exact pins
    package-lock.json
    tsconfig.json
    .nvmrc
    bin/publish_news.ts          CLI entry; Node runs .ts directly, no build step
    config/titles.yaml           per title: masthead, device profile, page budget, asset theme
    contracts/                   HAND-WRITTEN. The published interface block 2 builds against.
      edition-contract.v1.schema.json
      publication-receipt.v1.schema.json
      fit-report.v1.schema.json
      examples/                    golden documents; both blocks test against these
        minimal.json dense.json all-callout-kinds.json
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
        store.ts release.ts manifest.ts hash.ts atomic.ts lock.ts
      cli/
        main.ts args.ts
        actions/ list-actions.ts validate.ts fit.ts render-device.ts
                 build-web.ts publish.ts verify.ts doctor.ts
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
    tests/ unit/ golden/ fixtures/
    var/                         gitignored: runs/, build-input/, publish-root/
```

One package, no workspaces: one lockfile, one `node_modules`, no hoisting nondeterminism. Astro runs as
`npx astro build --root site`. Enforce the module boundary with a test that greps imports: `device/`
must not import from `site/`, and `site/` must not import from `device/`.

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

Do not author this in Zod and emit JSON Schema from it. Zod expresses constraints that JSON Schema
cannot carry, such as a refinement requiring a `quote` callout to name a speaker. Those constraints are
dropped or weakened in translation, so block 2 would validate against a weaker artifact than block 3
enforces, pass, write the file, and be rejected at the publishing end for a mistake made at the
editorial end. Astro's content collection still takes a Zod schema, but it only sees files block 3 wrote
itself after validation, so a permissive schema there is correct and carries no contract meaning.

`contracts/examples/` holds golden edition documents. Both blocks load them in their test suites: block
3 asserts it can consume them, block 2 asserts it can produce documents like them. These catch what a
schema cannot express and let each side detect a break without running the other.

### Versioning

Because block 3 owns the vocabulary, a careless block 3 change breaks block 2. Follow block 1's rule.
Evolve additively within a major version: a new callout kind, a new optional field, or a widened
composition range needs no coordination, and block 2 adopts it when it chooses. Removing a kind,
renaming a field, making an optional field required, or narrowing an enum is breaking and bumps
`schema_version`. Block 3 declares the versions it accepts and rejects others with
`contract_unsupported_schema_version`. Never change a published schema file in place.

Unknown fields are rejected. Every timestamp is RFC 3339 UTC with six fractional digits and a `Z`,
matching block 1.

### Identity, presentation, coverage

| Field | Meaning |
|---|---|
| `schema_version` | Integer literal `1`. Block 3 refuses versions it does not implement. |
| `title` | The publication this edition belongs to. Selects the masthead, device profile, and default page budget block 3 holds in `config/titles.yaml`. An installation may publish several titles, each with its own archive and latest pointer. |
| `edition.id`, `edition.revision` | Stable identity within the title. A correction increments the revision. |
| `edition.date`, `timezone`, `language`, `cutoff_at`, `generated_at` | Display date, display zone, output language, the "news through" time, and editorial generation time. |
| `edition.name`, `edition.number` | Masthead ear text such as "Afternoon brief", and the edition number. |
| `presentation.preferred_composition` | Optional hint: `lead-wide`, `lead-tall`, or `lead-centred`. |
| `presentation.emphasis` | Optional hint: `one_big_story`, `quiet_day`, or `many_stories`. |
| `presentation.ear_right` | Optional short line for the right masthead ear. |
| `coverage` | Feeds checked, feeds failed, and a status of `complete`, `partial`, or `unknown`. Rendered verbatim in the web edition. Block 3 never claims coverage the contract does not assert. |
| `inputs[]` | Block 1 bundle references and digests, carried into the manifest for provenance. |

### Stories

`stories[]` is ordered and authoritative. Block 3 never re-orders it.

| Field | Meaning |
|---|---|
| `id`, `revision`, `order` | Durable editorial story identity and position. |
| `required` | When true the story must appear on the device edition or the device build fails. |
| `kicker`, `kicker_secondary` | The small-caps label above the headline, and an optional second term. |
| `role` | `lead`, `secondary`, or `brief`. **Exactly one `lead` per edition**, always on device page 1. |
| `fallback_role` | Optional demotion target. `lead` has no fallback. |
| `copy.headline`, `copy.headline_short` | The headline and an approved shorter form for a narrow slot. |
| `copy.deck` | Optional italic standfirst. |
| `copy.body` | Object keyed `extended`, `standard`, `short`, each an array of paragraphs. All optional; a title-only item supplies none. Approved variants, not budgets block 3 may trim. |
| `callouts[]` | Zero or more candidates in priority order. |
| `sources[]` | Every contributing article: publisher, publisher id, article id, original title, URL, published time, content hash, and one flagged `primary`. |
| `limitations[]` | Evidence limitations such as `digest_of_rss_description`. |

### Callouts

| `kind` | Required fields |
|---|---|
| `quote` | `text`, `attribution` (the speaker), `attribution_source` (the reporting publisher) |
| `figure` | `value` (a short numeral string such as `8.4 bn`), `label` |
| `facts` | `title`, `items[]` of two to four short strings |
| `box` | `label`, `text` |
| `timeline` | `title`, `rows[]` of two to four `{date, text}` |

### Fit policy

`fit_policy` **constrains the device edition only**.

| Field | Meaning |
|---|---|
| `page_budget`, `page_maximum` | Target and hard ceiling for device pages. Defaults 1 and 2. |
| `allow_role_fallback`, `allow_composition_substitution` | Whether block 3 may demote a role or change composition to make an edition fit. |
| `reserve_story_ids[]` | Ordered stories block 3 may add if space remains. |
| `omittable_story_ids[]` | Ordered stories block 3 may drop from the device edition, first to last. A story not listed here is required on the device. |

### Validation beyond the schema

Exactly one `lead`. Every id in `reserve_story_ids` and `omittable_story_ids` exists. Every
`sources[]` has exactly one `primary`. Every URL is `https:`. `fallback_role` is never `lead`. Failures
are `contract_invalid` with the offending path in `error.details`.

## 6. What block 3 returns

**`fit-report.json`** records the whole device fit search: every composition considered and why it was
rejected, per-slot measurements, every repair the policy applied in order, every callout dropped, every
story omitted with its reason, and the list of any off-origin request the browser attempted. It is
diagnostic, and it is what block 2's LLM reads to shorten copy.

**`publication-receipt.json`** reports the two outputs separately, because they now differ.

- `web.story_ids[]` — every story published to a reader. **Block 2's repeat-suppression memory updates
  from this set.** A story that reached the website was published whether or not the panel had room.
- `device.status` — `published`, `failed`, or `skipped`.
- `device.story_ids[]`, `device.composition`, `device.pages`, and per story
  `{role_as_placed, page, slot, copy_variant, callout_kind}`.
- `device.omitted[]`, `device.dropped_callouts[]`, `device.structural_elements[]`.
- `bundle.path`, `bundle.manifest_sha256`.

**`manifest.json`** identifies the editorial edition and revision, the layout version, the device
profile, the renderer environment (Node, Astro, Playwright, Chromium version and path, ImageMagick,
fonts lock digest), page order, filenames, byte counts, and `sha256:`-prefixed hashes. Sorted keys,
compact separators, mirroring block 1's `export.py`.

## 7. Compositions and slot capacities

`src/device/catalog/` is the only place capacity is declared.

| Composition | Secondaries | Briefs | Callout slots |
|---|---|---|---|
| `lead-wide` | 2–3 | 3–4 | lead, any secondary |
| `lead-tall` | 1–3 | 0 | lead, any secondary |
| `lead-centred` | 3–4 | 4–6 | lead, any secondary with a standard-length body |

`one_big_story` prefers `lead-tall`, `quiet_day` prefers `lead-wide`, `many_stories` prefers
`lead-centred`. A composition whose ranges cannot cover the requested counts is rejected
arithmetically, before any render. Adding a fourth composition must not require touching the fit
engine.

**No pixel dimensions in TypeScript.** `device.css` owns every geometry number through custom
properties; the catalog names only slot ids, kinds, selectors, and count ranges. Measurement reads
computed geometry from the DOM, so a design change is a CSS change.

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

Three further rules, each enforced by a test over the CSS:

- Every text element sets an explicit `line-height`. Computed `line-height` is never `normal`.
- `device.css` uses no `:nth-child`, `:first-child`, `:last-child`, `+`, or `~` for layout, because the
  measurement probe clones a slot as a sibling and a clone shifts sibling indices.
- Every device colour token is `#XYXYXY` with `X == Y`, so it lands exactly on a 16-level step.

## 9. Measurement

One `Browser`, one `BrowserContext`, and one `Page` are reused across the whole fit loop. Fonts and CSS
come from the context cache after the first load.

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
stylesheet reference leaked.

**Settle sequence per candidate.** Navigate with `waitUntil: 'load'`, never `networkidle`. Await
`document.fonts.ready`, then assert each required face positively with `document.fonts.check()`, because
`fonts.ready` resolves happily when a face silently failed. Then await two nested
`requestAnimationFrame`s to guarantee a completed layout and paint. A missing face is `font_not_loaded`
with the face list in `error.details`.

**Navigate to a distinct URL per candidate**, `/c/<candidate-sha256>/p<N>.html` with `Cache-Control:
no-store`; assets at `/a/<layout-version>/**` with a long immutable max-age. A full document load resets
DOM, styles, and scroll, so nothing else needs resetting between candidates. Do not use
`page.setContent()`: relative URLs then resolve against `about:blank` and the CSS and fonts silently
404, which produces plausible-looking but wrong measurements.

### Overflow detection

The reliable test differs by slot kind, and this is the part most easily got wrong.

| Slot kind | Test | Why |
|---|---|---|
| Block flow (grid child) | `scrollHeight > clientHeight` | Reliable given the bounded-box invariant |
| CSS multi-column | `scrollWidth > clientWidth` | With a constrained height, overflow creates extra columns in the **inline** direction, so `scrollHeight === clientHeight` while the content is clipped |

Comparing the last child's bottom edge against the container's content box is **not** reliable and must
not be used: it misses content overflowing past the last child, it is fooled by collapsed margins, and
in multi-column the last child sits in the last column so its bottom is inside the box.

**Magnitude comes from a separate off-screen probe.** Clone the slot as a sibling, absolutely
positioned, hidden, unconstrained in height, single-column, and read its natural height. For a block
slot the probe width is `clientWidth` and available is `clientHeight`; for a multi-column slot the probe
width is `(clientWidth − (N−1)·gap) / N` and available is `N · clientHeight`. `overflowPx = natural −
available`.

Authority is split deliberately: `fits` comes from the in-place metric, which is exact;
`overflowPx` comes from the probe, which is actionable. For multi-column the probe understates slightly
when a column break leaves slack, so there `overflowPx` is advisory and `fits` is authoritative. Say so
in the fit report so nobody trusts the wrong number. For block slots assert `fits === (overflowPx <= 0)`;
disagreement is `measurement_inconsistent`, an internal bug in the CSS invariants rather than an edition
failure.

Add a three-pixel safety margin: `fits = measuredPx + 3 <= availablePx`. A one-pixel overflow clips a
descender, and `overflow: hidden` does it silently.

### One round trip

A single `page.evaluate` returns, per slot: `availablePx`, `measuredPx`, `overflowPx`, `lineHeightPx`,
`overflowLines`, `lineCount`, `headlineLines`, `fits`, `charsInBody`, and `suggestedMaxChars`. Inside
it: read all in-place metrics, append all probes, force one layout, read all probe heights, remove all
probes.

`overflowLines = Math.ceil(overflowPx / lineHeightPx)`, because lines are what an LLM can act on. Count
lines by clustering `Range.getClientRects()` by rounded `top`, since nested inline elements split one
visual line into several rects and a raw length overcounts.
`suggestedMaxChars = floor(charsInBody × availablePx / measuredPx × 0.97)` is an advisory hint with a
three per cent margin. Block 2 rewrites, block 3 re-measures; it is never a contract.

## 10. The fit policy

Word counts are rejected as a fitting mechanism: Danish compounds, long names, and translated headlines
make them unreliable. Every candidate is measured with the real fonts at the real size.

Repairs apply to the **first** failing slot in deterministic order — page ascending, then the
composition's declared slot order — and the ladder restarts after a structural change:

1. Drop the callout.
2. Step down one approved copy variant.
3. Apply `fallback_role`.
4. Substitute the next permitted composition. Restarts the ladder.
5. Move the story to a later page within `page_maximum`. Restarts the ladder.
6. Omit the lowest-priority story in `omittable_story_ids`, in the authorized order.
7. Fail with `fit_failed_required_story`, carrying the slot, the story, and the overflow in lines.

Callouts are the first thing removed and the last thing added, so a busy day loses emphasis before it
loses stories. Never shrink type, clip a paragraph, drop an attribution qualifier, or split a sentence
across device pages. A sparse day gets whitespace, never filler.

**Bounding.** A `visited` set keyed on the SHA-256 of the canonical JSON of each candidate prevents
cycles when steps 4 and 5 restart the ladder. Each alternative composition is entered at most once.
`maxCandidates` defaults to 40 and `maxWallClockMs` to 60 000; exceeding either is
`fit_budget_exhausted`. Every transition appends `{candidate, slot, action, before, after, measurement}`
to `fitReport.trace[]`, which is the audit trail a person reads when a page looks odd.

Warm page loads cost roughly 150 ms, so 40 candidates over at most two pages is about twelve seconds in
the worst case.

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
removes the only mechanism that could shrink the layout viewport. Multi-page editions use one document
and one URL per page; never stack pages in one document and clip. Assert the size from the PNG IHDR in
the buffer, not from Playwright: mismatch is `screenshot_size_mismatch`.

For the final capture, create a fresh context with identical options. It costs about 200 ms and
guarantees the published PNG was not produced by a page that dozens of measurement probes had touched.

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

Built from the validated contract alone. It does not wait on the fit loop, and it takes the fit report
as an **optional** input so it can say "page 2 of 2", link the device image, or note that a story did
not fit the panel. It must never claim a device page exists when `device.status` is not `published`.

**Routes.** `/` is the latest edition. `/archive/` is the index, newest first. `/n/<id>/` is an
immutable permalink. `/go/<id>/prev/` and `/go/<id>/next/` are shell-owned redirect stubs, using a meta
refresh with a real anchor fallback and no JavaScript, so an archived edition page never has to be
rewritten when a newer edition arrives.

**Content.** Every accepted story at the longest approved body variant, in editorial order. Every
approved callout, including those the panel could not hold. An expandable source list per story with
each contributing article's original title, publisher, and time. The coverage note verbatim. Per-story
anchors. A link to the device image when one exists.

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

Content arrives through a content collection whose loader globs `var/build-input/editions/*.json` and
whose Zod schema is deliberately permissive, since the CLI already validated these files against the
contract before writing them. The CLI writes the input files, then shells
out to `npx astro build`; the programmatic build API is also experimental and buys nothing here.

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
      device/page-N.html     the exact HTML that produced the PNG, auditable
      device/page-N.png      absent when the device build failed
    a/<layout-version>/      immutable shared assets, published by ONE rename
      device.css  web.css  fonts/*.woff2  OFL.txt
    index.json               append-only list of published editions
  releases/<run-id>/         the complete docroot for this run
    index.html  archive/  go/<id>/{prev,next}/  latest.json
    n/<id>/…                 HARDLINKS into store/n/<id>/
    a/<v>/…                  HARDLINKS into store/a/<v>/
    device/current.png       HARDLINK to the newest edition that HAS device pages
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
through a link.

**Partial success is allowed in one direction only.** If the device fit fails and the web edition
builds, publish the web edition with `device.status: "failed"` and **do not advance
`device/current.png`**. Its bytes and therefore its `ETag` and `Last-Modified` stay unchanged, so
TRMNL's conditional request returns 304 and the panel keeps the last good page rather than a gap.
Accept and state the visible consequence: the reader can see today's paper on the web while the panel
shows yesterday's. The reverse is not allowed — if the web build fails, publish nothing.

Default `publish` to partial publication with `result.status: "partial"` and exit 0, so a cron can
surface it. `--require-device` makes it strict: nothing publishes, exit 1, `fit_failed_required_story`.
Do not publish and exit 1 at once; that is the confusing middle.

## 14. Reproducibility, security, and configuration

**Pinning.** Exact versions, no ranges. `engines: { node: ">=26.0.0 <27" }`, `packageManager`, an
`.nvmrc`, and an `overrides` entry pinning `playwright-core` to the same version as `playwright`,
because the browser revision is tied to `playwright-core` and a transitive dependency could otherwise
change the renderer silently. Install only with `npm ci`.

Install the browser hermetically: `PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install --no-shell
chromium`. That places it under `node_modules/playwright-core/.local-browsers`, so another project
running `npx playwright install` cannot move this renderer. Record `browser.version()` and
`chromium.executablePath()` in the manifest; `verify` compares them and treats a difference as a
renderer change requiring visual regression.

**Fonts.** Vendor seven static-instance WOFF2 faces — Playfair Display 700, 900, and 700 italic; Source
Serif 4 400, 600, 700, and 400 italic — with `OFL.txt` and a `fonts.lock.json` recording each file's
SHA-256, byte count, upstream URL, and version. Static instances rather than variable fonts, because
variable rendering varies more subtly across browser builds and complicates `fonts.check()`. Do not use
Astro's Fonts API: it emits hashed filenames, which breaks the stable asset path, and generates metric
fallbacks, which is the wrong behavior in a system where a missing font must be a hard error. Two gates:
every file's hash matches the lock, and every `(family, weight, style)` used in the stylesheets has a
matching `@font-face` and appears in the measurement code's required-face list.

**Keep ICU out of the render path.** Format every date and number in Node, once, in the CLI, and write
the formatted strings into the frozen composition record, so a Node upgrade that changes `Intl` cannot
change a rendered page. Set `process.env.TZ = 'Europe/Copenhagen'`, inject the clock, and test frozen.
The context's `locale` and `timezoneId` stay set as defence in depth.

**Animations are disabled three ways**: `reducedMotion: 'reduce'` on the context, `animations:
'disabled'` on the screenshot, and `*, *::before, *::after { animation: none !important; transition:
none !important }` in `device.css`.

**Build determinism** is asserted, not assumed: build twice from the same input and compare file hashes.
Rolldown and Vite 8 chunk hashing should be deterministic but carries no documented guarantee, and the
gate also catches an accidental `Date.now()` in a template. Add a grep gate over `dist/`: no `http://`,
no `https://fonts.`, no protocol-relative URLs except inside `<a href>`, which are the real publisher
links and are never fetched.

**Configuration.** `config/titles.yaml` holds what belongs to a publication rather than to a day, keyed
by title id: masthead wording, device profile dimensions, default page budget, default composition
preference order, and the publisher-id to display-name mapping. Block 2 supplies the day and names the
title; block 3 supplies that title's identity. A title block 3 does not know is `resource_not_found`,
not a guess. Display only publishers that actually contributed to the edition.

Titles are independent all the way down. Each gets its own archive, latest pointer, device pointer, and
store prefix, so one title's failed build cannot disturb another's. Adding a title is a config entry
plus a masthead, not a code change.

Reproducibility means the same composition and pinned environment yield stable artifacts. It does not
promise byte-identical PNGs across operating systems or browser upgrades.

## 15. CLI contract

One POSIX `sh` wrapper, `publish_news.sh`, self-locating, emitting a `dependency_missing` envelope when
`node_modules` is absent and otherwise execing `bin/publish_news.ts`. Node runs TypeScript directly, so
there is no build step for the CLI; `tsc --noEmit` is the typecheck gate. It is the only entry point;
do not invoke `npm`, `node`, or `astro` directly.

Stdout is exactly one compact key-sorted JSON object per invocation, matching block 1's shape:

```json
{"ok":true,"action":"publish","result":{},"meta":{"cli_version":"0.1.0","schema_version":"1.0"}}
```

Exit `0` on success, `1` on a well-formed action that failed, `2` on a usage error.

| Action | Mutates | Purpose |
|---|---|---|
| `list-actions` | no | Sorted, self-describing catalog for an LLM caller |
| `schema` | no | Print a contract file from `contracts/` by name, so block 2 can pin a copy |
| `validate` | no | Schema and invariant check on an edition file |
| `fit` | no | Run the measured fit loop and emit the fit report; write no artifacts |
| `render-device` | yes | Capture and convert from a frozen composition |
| `build-web` | yes | Build the web edition from a contract and an optional fit report |
| `publish` | yes | Full pipeline into the store and a new release |
| `verify` | no | Re-check every hash and invariant in a published bundle |
| `doctor` | no | The pinning report: Node, Astro, Playwright, Chromium version and path, ImageMagick, fonts digest, layout version |
| `version` | no | CLI and schema versions |

`fit` is the action block 2's LLM calls in a loop. It is read-only, needs no output directory, and its
report names the slot, the story, and the overflow in lines. `doctor` is what gets pasted into a bug
report and what `verify` compares against.

Stable snake_case error types: `usage_error`, `contract_invalid`,
`contract_unsupported_schema_version`, `composition_unavailable`, `fit_failed_required_story`,
`fit_budget_exhausted`, `measurement_inconsistent`, `font_not_loaded`, `render_timeout`,
`screenshot_size_mismatch`, `quantize_failed`, `image_invariant_violation`, `network_access_blocked`,
`web_build_failed`, `asset_version_conflict`, `bundle_exists`, `publish_conflict`, `lock_busy`,
`renderer_unavailable`, `dependency_missing`.

`--dry-run` on `publish` runs the whole pipeline into the staging directory, emits the manifest it would
publish, and removes the staging directory, matching block 1's `plan_export` semantics.

## 16. Work packages and completion gates

Three milestones sit inside the sequence. **WP 1–5 produce a working newspaper website** from a fixture,
with no device work at all. **WP 6–10 add the panel** and the store that carries both. **WP 11–14 harden
it** and prove it on the device. The web edition leads because it is the product.

**WP 1 — Skeleton, CLI envelope, and `doctor`.** `publish_news.sh`, `package.json` with exact pins and
the `playwright-core` override, `tsconfig.json` with `erasableSyntaxOnly`, `bin/publish_news.ts`, the
action catalog, envelope, exit codes, and error types. Implement `list-actions`, `version`, `doctor`.
*Complete when* the wrapper runs from outside the repository, `list-actions` is sorted and
self-describing, a usage error exits 2 with a JSON envelope, stdout is a single object in every case,
and `npm ci` from a clean clone reproduces the `doctor` report on this machine.

**WP 2 — Contract schema and validation.** Section 5 as hand-written JSON Schema in `contracts/`, the
golden documents in `contracts/examples/`, generated TypeScript types, an Ajv validator, and the
`schema` and `validate` actions. *Complete when* every golden document and every fixture validates,
unknown fields are rejected, each Section 5 invariant is rejected with `contract_invalid` naming the
JSON pointer to the offending value, an unsupported `schema_version` is rejected distinctly, and the
generated types compile against every golden document without a cast.

**WP 3 — Design layer and fonts.** Vendored WOFF2 faces with `OFL.txt` and `fonts.lock.json`,
`tokens.css`, `device.css`, `web.css`, and the escaping and markup helpers, ported from
`design/device.html`. *Complete when* every font hash matches the lock, every `(family, weight, style)`
in the stylesheets has an `@font-face`, every device colour token is `#XYXYXY` with `X == Y`, and a fuzz
test injecting `<script>`, `&`, `"`, and `</div>` into every contract string field produces no
unescaped `<` and no `<script` in output.

**WP 4 — Web edition.** Section 12: Astro config set explicitly, content collection, layouts,
components, routes, redirect stubs, coverage note, archive index, latest pointer. *Complete when* a
fixture builds to a site containing every story and callout at full length, links resolve, the page
reflows to one column at 400 px, the CSP meta tag is present, `dist/` contains no `http(s)://` outside
`<a href>`, and two builds from the same input produce identical file hashes.

**WP 5 — Store and release.** Section 13: staging, hashing, sorted-key manifest, per-edition rename,
hardlinked releases, symlink swap, `verify`, and `build-web` and `publish` with `--dry-run`. *Complete
when* an edition directory appears through exactly one rename, the docroot swaps through exactly one
symlink rename, every release file is a hardlink to a mode-0444 store file, an existing target yields
`bundle_exists`, a crash injected at each stage leaves either no edition or a complete one, and `verify`
re-checks every hash.

**WP 6 — Device compositions.** `catalog/`, `render.ts`, `server.ts`, and the three compositions behind
a fixed 1872 × 1404 frame with no links and no scripts. *Complete when* each renders from a fixture at
exactly the target size, matches the corresponding image in `design/preview/` on visual inspection, and
the rendered HTML contains no `<script`.

**WP 7 — Measurement harness.** Section 9: browser lifecycle, loopback server, route blocking, font
assertion, settle sequence, and the single-evaluate probe. *Complete when* every slot has
`overflowY: hidden` and a resolved `min-block-size` of 0, no computed `line-height` is `normal`,
`device.css` contains no structural selectors, `fits === (overflowPx <= 0)` for every block slot,
measuring one candidate twice returns identical numbers, and a deliberately clipped multi-column body is
detected through `scrollWidth`.

**WP 8 — Fit policy.** Section 10: the bounded state machine, the visited set, the budgets, the trace,
and the `fit` action. *Complete when* each rung of the ladder is exercised by its own fixture, the trace
records every transition in order, budget exhaustion is reachable and reported as
`fit_budget_exhausted`, and the required-overflow fixture fails with `fit_failed_required_story` carrying
the slot and the overflow in lines.

**WP 9 — Capture and conversion.** Section 11. *Complete when* the PNG buffer's IHDR is 1872 × 1404 at
bit depth 4 and colour type 0, the chunk set is exactly `{IHDR, IDAT, IEND}`, `identify` returns
`1872 1404 4 <=16 Grayscale`, every histogram level is a multiple of 17, ten consecutive captures of one
frozen composition are byte-identical, and two conversions of one master are byte-identical.

**WP 10 — Device failure path.** Wire `device.status` through the receipt, the manifest, and the web
template. *Complete when* an edition that cannot fit publishes the web bundle with
`device.status: "failed"`, `device/current.png` still resolves to the previous edition with unchanged
bytes and mtime, the web page renders no device affordance, `publish` exits 0 with
`result.status: "partial"`, and `--require-device` instead publishes nothing and exits 1.

**WP 11 — Test suite and `check`.** Section 17, plus a `check` action shelling out to lint, `tsc
--noEmit`, tests, and `sh -n` on the wrapper with bounded output tails. *Complete when* `check` passes
from a clean checkout with no network access.

**WP 12 — First-edition validation.** Build one real edition from a hand-written contract based on
actual block 1 output. Compare against `design/preview/` at the physical device size, then load the PNG
on the TRMNL X. *Complete when* the panel shows a legible page, every callout kind survives
quantization, and the receipt describes exactly what was published.

**WP 13 — Variation review.** Generate seven consecutive editions spanning dense, sparse, long-headline,
Danish-text, missing-description, and partial-coverage cases. *Complete when* they differ in
composition, role counts, and callouts while type sizes, margins, rules, and palette are identical
across all seven.

**WP 14 — Delivery adapter interface.** A thin adapter around page URLs and publication status, and a
local server serving the current page with `ETag` and `Last-Modified` validators that change with the
image bytes. No hosting, no account configuration. *Complete when* a conditional request for an
unchanged page returns 304 and a republished edition returns 200 with new validators.

## 17. Test and fixture policy

Every default test is network-free and uses temporary directories. Fixtures in `tests/fixtures/` are the
reason block 3 is buildable and testable before block 2 exists: `dense`, `sparse`, `long-headline`,
`danish`, `missing-description`, `all-callout-kinds`, `required-overflow`, `partial-coverage`.

- **Contract** — table-driven acceptance and rejection, including exactly-one-lead and each callout
  kind's required fields.
- **Escaping** — the fuzz test from WP 3, run against every string field.
- **CSS invariants** — the four stylesheet rules in Section 8, asserted by parsing the CSS.
- **Measurement** — determinism, the block and multi-column overflow paths, and the cross-check.
- **Fit** — one fixture per rung, asserting on the recorded trace rather than on message wording.
- **Image** — IHDR bytes, chunk set, `identify` output, histogram levels, and conversion determinism.
- **Web** — every contract story present, links resolve, no remote origin, build determinism.
- **Visual regression** — checked-in reference PNGs for the three compositions and the web edition at
  two widths, compared with a pixel tolerance, run before any renderer or Astro upgrade.
- **Boundary** — `device/` does not import from `site/`, and `site/` does not import from `device/`.
- **Smoke** — shell out to `publish_news.sh publish` from outside the repository and assert on the
  parsed envelope and the files on disk.

Assert structured fields, never human log wording. Freeze or inject clocks; do not sleep.

## 18. Acceptance criteria

1. `publish_news.sh check` passes from a clean checkout with no network access.
2. `validate` rejects every Section 5 invariant violation with `contract_invalid` and the offending path.
3. `fit` on the same fixture twice returns identical reports.
4. `fit` on `required-overflow` exits 1 with `fit_failed_required_story` naming the slot and the
   overflow in lines.
5. Every device PNG is 1872 × 1404, colour type 0, bit depth 4, at most 16 levels each a multiple of 17.
6. Ten captures of one frozen composition are byte-identical; two conversions of one master are
   byte-identical; two web builds from one input have identical file hashes.
7. Every story and callout in the contract appears in the web edition at full approved length.
8. The web edition reflows to one column at 400 px with story order and attribution preserved.
9. No built file and no rendered page references a remote origin; the fit report's off-origin list is
   empty.
10. A device fit failure publishes the web edition, leaves `device/current.png` byte-unchanged, and
    reports `result.status: "partial"`.
11. An edition directory is published by exactly one rename; the docroot swaps by exactly one symlink
    rename; `verify` re-checks every hash.
12. Re-publishing an existing edition id fails with `bundle_exists` and changes nothing.
13. The receipt's web story set is a superset of its device story set.
14. Seven consecutive fixture editions differ in composition, role counts, and callouts, with identical
    type sizes, margins, rules, and palette.
15. A real edition is legible on the TRMNL X at arm's length, with every callout kind surviving
    quantization.

## 19. Explicit deferrals

Publisher photography and any remote asset path. A CMS, including Keystatic, which would also need a
version compatible with Astro 7. Paged.js, flowing article text, and PDF output. A portrait device
profile. Hosting, TRMNL account configuration, and any network delivery beyond the local adapter in
WP 14. Human override tooling. Search over the archive. A containerized build, which stays available but
is not built now.

## 20. Open questions to settle by spike, not by argument

Each of these was researched and left unresolved; each has a work package that answers it empirically.

1. **CSS multi-column overflow reports through `scrollWidth`.** This is what the multi-column spec
   requires and what browsers are believed to do, but it was not run. Spike it before WP 7, because it
   decides the `lead-tall` measurement path.
2. **The three Chromium font-rendering flags.** Widely used for screenshot stability but absent from
   Playwright's documentation. WP 9's ten-identical-captures gate settles them; drop any flag that does
   not change the hash.
3. **Rolldown and Vite 8 build determinism.** No documented guarantee was found. WP 4's build-twice gate
   answers it.
4. **`page.screenshot({ scale })` default.** The Playwright docs contradict themselves. Moot at
   `deviceScaleFactor: 1`, and set explicitly regardless.
