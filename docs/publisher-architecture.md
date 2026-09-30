# Block 3: the publisher

Status: as-built documentation, describing block 3 as it stands on 30 September 2026. Companions:
[Block 1: ingestion architecture](ingest-architecture.md), [Block 2: editorial architecture](editorial-architecture.md),
the [decision log](decision-log.md), and the [roadmap](roadmap.md) for what is designed but not built.
Commands and failure handling: [publisher/README.md](../publisher/README.md), [publisher/OPERATIONS.md](../publisher/OPERATIONS.md).

## What block 3 is

Block 3 is a static edition publisher in `publisher/`: TypeScript on Node 26, Astro 7 for the web
edition, a plain TypeScript template for the device page, a pinned Playwright Chromium for measurement
and capture, and ImageMagick 7 for the device image. From one accepted edition it produces two outputs.
The web edition is the product: a static broadsheet site carrying every story at full approved length,
with per-edition permalinks, an archive, and a latest pointer. The device edition is a reduced artifact:
one 1872 by 1404 sixteen-level grayscale PNG for a TRMNL X panel. The two share the edition, the
type, and the story and callout components, and nothing else: no layout, page budget, or build path.

Boundary rules, enforced by the tests in `publisher/tests/`: block 3 calls no model, it selects among
the copy variants block 2 supplied and measures boxes, never rewriting, shortening, reordering, or
composing. It renders only its own pages from local assets: the device browser loads pages from a
loopback server, aborts every off-origin request, and fails the run if one was attempted; it never
visits a publisher URL. It uploads nothing and touches no account; delivery belongs to the desk. Every
contract string is escaped before it reaches a template.

## The edition contract

The edition is the publishing unit. Its shape is `contracts/edition-contract.v1.schema.json`, a
hand-written JSON Schema 2020-12 owned by block 3; the TypeScript types are generated from it, never
the reverse, so Python and TypeScript validate one artifact identically. Golden editions and a
rejection corpus are in `contracts/examples/`, beside the schemas for what block 3 writes. Story
order in the contract is authoritative; a story has a role (lead, secondary, brief), up to three body
variants, an optional short headline, callouts of five kinds (`quote`, `figure`, `facts`, `box`,
`timeline`), and complete sources. `config/title.yaml` holds what belongs to the title rather than
the day: id, masthead, device profile, web composition, and the publisher id to display name map.

`validate` reads at most 4 MiB of UTF-8 JSON, accepts only `schema_version` 1, validates with Ajv in
strict mode with full format checking, then applies the semantic rules in `src/contract/edition-contract.ts`:
the title matches the configured id; ids are unique; exactly one lead, first, `required`, without a
fallback; only a secondary may fall back to brief, and anything that can be a brief has a lede; a
sourced story has one primary source, every source names a configured publisher and an existing input
over HTTPS, and every citation names one of the story's sources; the fit policy's lists match the
`reserve` and `optional` stories exactly; and the coverage status agrees with the feed inventory.

## The web edition

Astro runs once per edition in a scratch directory, with `TZ=Europe/Copenhagen` and
`SOURCE_DATE_EPOCH=0`. Only that edition is in the content collection; the archive, the latest
pointer, and the `go/<id>/prev|next` stubs are built from the store's index snapshot, the only way the
build can know about editions it does not render. Every page links its stylesheet at
`/a/<layout version>/web.css`; the layout version is `broadsheet-v3` (`src/contract/version.ts`).
Assets are `tokens.css` concatenated with `web.css` or `device.css` plus the vendored variable WOFF2
files of Newsreader and Libre Franklin; no font loads from the network.

Two compositions exist; `web_layout` in the title config selects one, and `--layout` overrides it for
`build-web` and `preview` only. Both render the same `Story` component and one type scale.

- Grid, the default: the lead, body in two columns, beside a rail of up to two secondaries. The rest,
  secondaries then briefs under an "Also today" head, are dealt at build time into three fixed,
  contiguous stacks by `assets/html/columns.ts`, which estimates each story's height from a scale
  calibrated against rendered editions, not balanced CSS columns, so opening a source list only
  pushes down the stories beneath it.
- Sheet: one sheet of three balanced CSS columns. The lead's kicker, headline, and deck span them;
  its body and everything else flow through in contract order.

The masthead's left ear is the weekday edition label ("Monday edition") and "News through 8am, 28
September", both read off the cutoff in the edition's timezone, in Danish for a Danish edition. The
right ear is the edition's `ear_right` when block 2 supplies one, else "Edition N". The dateline
carries the date, the paper's number, and the five publishers that contributed to the most stories
with a "+N more" tail. The navigation line links the previous and next editions through the `go/`
stubs, the archive, and, when the edition has a device page, "View as printed page" at
`/n/<id>/device/page-1.png`, an edition-absolute link that stays right in the archive.

Each story renders its longest supplied body variant, justified, soft-hyphenated at build time from
TeX patterns for the edition's language (`config/hyphenation.json`) so every browser breaks words at
the same points, with a drop cap on the lead. The headline links to the primary source; the first
callout follows the header, the rest follow the body. Paragraph citations are not rendered inline;
the footer is one line naming every contributing publisher once, primary first, which opens a
disclosure with the limitations note and every article with its original title, publisher, and time.
The web adds a warm paper tone and one dark-red accent, which `web.css` uses for link hover and
focus, the pull-quote rule, the source-list toggle marker, the titles of facts, box, and timeline
callouts, the edition id in the folio, and the latest marks in the archive. The archive is a register
of back numbers, newest first and grouped by month: each row shows the paper's own number (carried in
the index entry; position is the fallback for older entries), the day, and the name.

## The store and activation

Publication is durable without a database. Under the publish root:

```
store/n/<edition-id>/   immutable bundle: edition.json, page, manifest, receipt, and the device files
store/a/<layout>/       immutable shared assets, one directory per layout version
releases/<release-id>/  a complete docroot of hard links into the store
live -> releases/<id>   the docroot delivery syncs
state/pending.json      the one durable activation intent, or absent
state/activations/      one record per activation, <release-id>.json, numbered by sequence, kept forever
.lock                   exclusive directory lock for publish and recover
.staging-<release-id>/  run-owned work, kept only while an intent is pending
```

`publish` takes the lock, refuses to run while an intent is pending, and refuses a stored edition
id. It renders the device page, builds the web edition, writes the bundle and its manifest (file
hashes, the shared asset inventory, the device outcome, and the renderer environment down to the
Chromium executable digest and the fonts lock), and assembles the release: hard links to every stored
edition and to this bundle, hard links to every layout version in the store so archived pages keep
the stylesheet they were published with, `index.json`, `latest.json` with separate web and device
pointers, `device/current.png` linked to the newest edition with a device page, and a root
`index.html` linked to the latest edition's own page.

The staged tree is synced to disk and the intent written atomically. Promotion renames each staged
object to its final path and freezes it read-only. Activation renames a temporary symlink over `live`
after checking that `live` still points at the recorded predecessor; a leftover temporary link with
this run's release id is replaced, anything else there is a conflict. The activation record gets the
next sequence number and the intent is removed. A crash before the intent leaves nothing; after it,
`recover` verifies every staged or promoted object against the intent's hashes, finishes promotion
and the swap, and, when a record for the release already exists from a crash between writing it and
clearing the intent, only cleans up. Releases beyond the newest five are then deleted, never the
live one; the store and records stay.

`receipt` returns the stored receipt only for an activated edition, after checking that the bundle's
manifest still hashes to what the activation record recorded. Block 2 advances its "already covered"
memory from this, never from a build or fit. `verify` re-hashes every bundle file and shared asset
against the manifest, and the manifest against the activation record when one exists. Archived
editions are never rebuilt: a correction appears in the next edition, and a design change applies
only to editions published after it.

## The device page

One composition, `lead-wide`, is built: masthead, a lead that is kicker, headline, deck, and source
line with an optional callout to its right, a band of up to three secondaries, a strip of up to four
briefs, and a folio with the cutoff and coverage status. The bands size to their content and the lead
takes what remains, so a too-full page shows as a clipped lead. Every geometry number is in
`device.css`; the template emits no links or scripts and links the stylesheet at
`/a/<layout version>/device.css`, the path the release serves.

`fit` places required and optional stories in contract order, repairing a band over capacity by
omitting optional stories from it, demoting a secondary with a brief fallback, then omitting any
optional story. The page is then measured and repaired down the fixed ladder the README describes
until it fits or a required story cannot be placed. A restoration phase then puts things back one at
a time and keeps each only if the page still fits: demoted secondaries get their role back, then
omitted optional stories most prominent first, then reserves in declared order, then dropped
callouts, within a budget of 80 candidates. Every transition is recorded in the fit report, stored
with the edition (on a failed fit too) so block 2 can shorten copy and retry rather than guess.

Measurement uses one pinned Chromium installed under `node_modules` with `PLAYWRIGHT_BROWSERS_PATH=0`
and a 1872 by 1404 viewport; pages are served from a loopback server, and all four required faces
must report loaded. Capture re-measures the frozen page and requires an identical result, takes one
viewport screenshot, and asserts the frame from the PNG header. ImageMagick converts it with
`-strip -colorspace Gray -depth 4`, no dithering, and the bytes are verified: 1872 by 1404, colour
type 0, bit depth 4, only IHDR, IDAT, and IEND, at most sixteen levels. `-strip` is what makes two
runs byte-identical; identity across operating systems or browser upgrades is not promised.

A device failure of capacity or availability publishes the web edition anyway as `status: "partial"`,
with the cause in the receipt and `device/current.png` still pointing at the last edition that
produced a page; `--require-device` reverses that. The four `DEVICE_INTEGRITY_ERRORS`
(`measurement_inconsistent`, `screenshot_size_mismatch`, `image_invariant_violation`,
`network_access_blocked`) always stop the run. If the web build fails, nothing is published.

## The command line

`publish_news.sh` is the public interface. Every action writes one JSON envelope on stdout; a usage
error exits 2, any other error 1. Options are strict (`src/cli/options.ts`): each action declares its
options and whether they take a value, and an unknown, repeated, or valueless option, or any
positional argument, is refused before the action runs, so a misspelt flag is never ignored on the
way to a publish. `preview` serves any edition on the loopback interface from a scratch build, with
real archive navigation when `--publish-root` is given, and writes nothing to the store.

## Unlisted posture and delivery

The site is served but not listed: every page carries
`<meta name="robots" content="noindex, nofollow, noarchive, noimageindex">`, the release root carries a
`robots.txt` that disallows everything, and CloudFront adds an `x-robots-tag: noindex` header for files
that are not HTML. Block 3 does none of the delivery. After an activated publish the desk syncs `live/`
to the S3 bucket and invalidates the CloudFront distribution, then copies `live/device/current.png` to
the NAS with `scp -O`; see [editorial/OPERATIONS.md](../editorial/OPERATIONS.md) and
[aws-delivery.md](aws-delivery.md). Publisher licensing is the open question behind the unlisted posture.

## Decisions and what remains

The decisions behind the above are in the [decision log](decision-log.md) with the alternatives:
block 3 owns the hand-written schema; Astro renders the web only, its container rendering being the
wrong tool for a fixed-size measured page; the web edition is first class and the device a reduced
artifact; immutability is a file protocol and activation the only evidence of publication.
Edition revisions with correction notices, a staging paper, whole-release verification in recovery,
multi-page device output, and further compositions are designed in the [roadmap](roadmap.md).
