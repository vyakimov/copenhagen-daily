# Block 3 code review — 30 September 2026

Reviewed through commit `3c9e8ce3f2986dcd5729aaf539a7c024ac1193e8`.

At final status inspection, concurrent uncommitted preview-command work appeared in `publisher/bin/publish_news.ts`, `publisher/src/cli/actions/list-actions.ts`, `publisher/src/publish/store.ts`, and `publisher/tests/web-store.test.ts`. Those changes were not made by this review and are outside this report's reviewed snapshot. Line references and check results refer to the reviewed implementation, before that in-progress work.

## Conclusion

The publisher has a sound basic architecture: block separation, strict edition validation, escaped static HTML, local-only device rendering, immutable bundles, and a journaled publication protocol. The new fixed web columns and heading grouping address the source-expansion issue. The archive-numbering change that arrived during this review also passed a targeted check.

However, I found **eight actionable issues**, including two crash windows that prevent recovery from completing, insufficient verification of the release being activated, and a device selection algorithm that can reject an edition that fits. I recommend fixing the recovery issues first. Passing the existing suite does not establish the stronger crash-recovery and archive-integrity guarantees described in the operations documentation.

No implementation, configuration, or test files were modified. This report is the only repository file added by the review. All experimental publications and corruptions were confined to newly created temporary directories; no live publication was accessed or changed.

## Findings

### 1. P1 — Recovery leaves a pending intent behind if the activation record already exists

**Location:** `publisher/src/publish/store.ts:394–413`, especially the early return at line 400.

`recordActivation()` returns immediately when it finds the release's activation record. It therefore skips removing `state/pending.json`. A process can die after the activation record is durably written but before pending-intent deletion. On the next recovery, the existing record is found, recovery reports success, but the pending intent survives. Subsequent publication and receipt reconciliation remain blocked with `recovery_required`.

**Verified reproduction:** Publish a temporary edition, then recreate the pending intent from the retained activation record, excluding `activated`, `sequence`, and `activated_at`. This materializes the journal state at that crash boundary. `recover` returned `status: recovered`; `state/pending.json` remained; `receipt` returned `recovery_required`.

**Recommended correction:** Make pending-intent cleanup and directory fsync happen on both the existing-record and new-record paths, after validating that the existing record belongs to the intended activation.

**Regression test:** Start with both a matching activation record and pending intent. Recover twice; the first call must remove the intent without incrementing sequence, and the second must report nothing to recover. Receipt and subsequent publication must work.

### 2. P1 — A crash after creating the temporary live symlink makes recovery fail with EEXIST

**Location:** `publisher/src/publish/store.ts:388–390`.

`swapLive()` creates a deterministic `.live-<release-id>` symlink before renaming it over `live`. If the process dies between these operations, recovery tries to create that same symlink again and fails with `EEXIST`. The documented stale-lock cleanup followed by `recover` does not resolve this state. The error is additionally mislabeled `usage_error` by the CLI fallback.

**Verified reproduction:** Publish with `--crash-at after-intent` in a temporary root, create the expected temporary symlink pointing to `intent.final.release`, then recover. Recovery promoted the objects but failed at symlink creation with `EEXIST`.

**Recommended correction:** Make temporary-symlink creation retry-safe. Validate and reuse a matching existing link, or safely replace the run-owned temporary link before performing the atomic rename. Do not replace unrelated paths blindly.

**Regression test:** Inject a failure between symlink creation and rename, then confirm recovery activates the intended release and removes temporary state.

### 3. P1 — Recovery can activate a corrupted release shell

**Location:** `publisher/src/publish/store.ts:833–889`; intent construction around lines 714–729.

Recovery verifies the candidate bundle, shared assets, and the candidate manifest's copy in the release. It does not verify the release shell's `index.json`, `latest.json`, archive, navigation pages, root index, or complete set of historical links. The intent contains no digest inventory for those shell files. A correct candidate manifest is insufficient evidence that the assembled docroot is intact.

**Verified reproduction:** Publish with `--crash-at after-intent`; replace the staged release's `index.json` with `{broken`; run `recover`. Recovery returned success and activated the invalid index. The next normal publication will fail while parsing that live index.

**Recommended correction:** Record a digest inventory for the complete release, or for its shell plus verifiable references to all bundled content, in the durable intent. Validate that inventory before activation, including file presence and internal references. Preserve failure evidence without changing `live` on verification failure.

**Regression test:** Independently corrupt or remove each shell artifact after durable intent, then assert recovery rejects it without switching `live`. Include root HTML, index metadata, navigation, and the current device pointer.

### 4. P2 — Archive verification trusts a modified manifest instead of the retained activation digest

**Location:** `publisher/src/publish/store.ts:952–975`; related receipt path at lines 938–948.

`verifyBundle()` reads the current manifest and verifies only the files that this manifest lists. It does not compare the manifest itself with the digest in the retained activation record, validate its schema, or require the expected bundle files. Removing file records from a parseable manifest removes those files from verification. `activatedReceipt()` likewise returns the current manifest digest and receipt without checking them against the activation evidence.

**Verified reproduction:** In a temporary published bundle, make the manifest writable, change `files` to an empty array, and replace `index.html` with `broken edition`. `verify` still returned `valid: true` and a new manifest digest despite the retained activation record containing the original digest.

This is an integrity-check gap, not a claim that file permissions protect against a malicious filesystem owner. Accidental modification or an incorrect restore should be detected relative to the separately retained activation record.

**Recommended correction:** For activated editions, verify the manifest digest against the activation record before trusting its inventory. Validate schemas, required files, and references. Apply corresponding checks to activated receipt reconciliation so downstream consumers do not accept changed content as the recorded publication.

**Regression test:** Modify only the manifest, remove a file record, alter a receipt, and remove a required file. Each must fail verification or reconciliation with an integrity error.

### 5. P2 — Capacity repair demotes secondaries even when the brief band is already over capacity

**Location:** `publisher/src/device/fit.ts:120–140`.

Whenever placement fails its role counts, `settle()` attempts `demote()` before omitting an optional story. `demote()` does not check which role is over capacity or whether the brief band has room. This can convert a required secondary into an additional required brief, making a recoverable count overflow impossible to resolve.

**Verified reproduction:** Construct a valid edition with one required lead, one required secondary eligible for brief fallback, four required briefs, and one optional brief. Use short copy so geometry fits. With `allow_role_fallback: true`, `fit` fails with `composition_unavailable`: the secondary is demoted, then the optional brief is omitted, leaving five required briefs. With the same edition and `allow_role_fallback: false`, `fit` succeeds by omitting the optional brief and retaining the secondary in its original band.

Ordinary `publish` can consequently produce an unnecessary web-only partial publication; `--require-device` will reject the whole run.

**Recommended correction:** Make role-count repair aware of the overflowing role and destination capacity. Avoid irreversible demotions that worsen the count problem; preserve or restore the prior role assignment when a fallback cannot produce a feasible placement.

**Regression test:** Cover the reproduction above and combinations with full brief bands, excess secondaries, and optional stories in either band. Enabling fallback should not destroy an otherwise feasible selection.

### 6. P2 — The homepage's printed-page link resolves to a nonexistent file

**Location:** `publisher/site/src/components/Masthead.astro:24`; root-page hardlink assembly in `publisher/src/publish/store.ts:684–692`.

The device link is `./device/page-1.png`. It works at `/n/<edition-id>/`, but the same HTML is hardlinked to `/`. At the homepage, the browser resolves it to `/device/page-1.png`. The release supplies `/device/current.png` and `/n/<edition-id>/device/page-1.png`, not `/device/page-1.png`.

**Verified reproduction:** Publish the minimal fixture with a device page. The homepage contains that relative link; its docroot target is absent; the edition-relative target exists.

**Recommended correction:** Use an edition-specific absolute URL, `/n/<edition-id>/device/page-1.png`, so the identical immutable HTML works at both addresses and refers to the edition being read.

**Regression test:** Resolve every local link from both the homepage URL and the edition URL against the assembled release. Include a backdated publication.

### 7. P2 — Saved device HTML references an asset URL that exists only in the renderer

**Location:** `publisher/src/device/render.ts:27`; `publisher/src/device/browser.ts` asset map; `publisher/src/publish/web.ts` asset copying.

Device HTML references `/a/device.css`. That URL exists on the ephemeral loopback rendering server. Published assets instead live under `/a/broadsheet-v3/`, and the stored HTML is copied without adjusting its reference. The archived `device/page-1.html` therefore cannot load its stylesheet from the published docroot. Standalone `render-device` output also does not include the referenced CSS and fonts.

**Verified reproduction:** Publish the minimal fixture with a device page. Saved device HTML references `/a/device.css`, while that path is absent from the release. The PNG still renders correctly because capture occurs on the loopback server where the URL exists.

**Recommended correction:** Give the frozen device HTML stable, versioned asset URLs and serve those same paths during capture, or bundle its assets with suitable relative references. Make standalone output's asset requirements explicit and usable as well.

**Regression test:** Check saved HTML asset references against the published release and standalone output, rather than testing only the renderer's private asset map.

### 8. P2 — Unknown CLI options are silently ignored, including a misspelled dry-run flag

**Location:** `publisher/src/cli/args.ts:3–20`; option handling in `publisher/bin/publish_news.ts`.

The parser collects arbitrary options and positionals, and the dispatcher never validates them against the action's supported arguments. Boolean options can also consume values, and duplicate options overwrite earlier values. The most consequential case is an operator believing a publication is a dry run when the intended flag is misspelled.

**Verified reproduction:** `validate --edition <fixture> --not-a-real-option` succeeds. In a fresh temporary root, `publish --edition <fixture> --publish-root <root> --skip-device --dryrun` returned `published` and created `live`; the unsupported `--dryrun` was silently ignored.

**Recommended correction:** Validate allowed option names, arity, duplicate options, and unexpected positionals per action before any filesystem mutation. Reject unsupported spellings with exit 2 and the existing JSON usage-error envelope.

**Regression test:** Include `--dryrun`, unknown flags, missing values, values supplied to boolean flags, duplicate options, and stray positionals. Invalid publish arguments must leave the target root untouched.

## Verification performed

- Ran `./publisher/publish_news.sh check`, including a repeat after commit `3c9e8ce` arrived. Lint, TypeScript, all existing tests, and shell-wrapper checks passed.
- Used only the public wrapper for experimental validation, fitting, publication, recovery, and verification. Python prepared fixtures and temporary filesystem states; no application source was changed.
- Exercised the pinned Chromium/ImageMagick path through the full suite and the targeted device probes. No publisher URL or remote page was loaded.
- Reproduced findings 1–8 using temporary roots or validated fixtures as described above. Crash-window probes materialized the relevant on-disk states; they were not real power-loss tests.
- Verified the concurrent archive-numbering fix using an edition numbered 42. Both its archive entry and edition page displayed `No. 42`.
- Reviewed the fixed-column implementation and heading grouping. Those remain sound for the grid composition's current inputs. `broadsheet-v3` is accepted as the new unpublished layout version per the user's clarification; no version-conflict finding is raised.

Temporary evidence retained for inspection:

- `/private/tmp/block3-review-pl98gvcp/results.json`: activation cleanup, release corruption, manifest verification, and archive numbering.
- `/private/tmp/block3-device-review-8w76xil3/results.json`: full fit responses and published-link checks; adjacent JSON files contain the validated capacity fixtures.
- `/private/tmp/block3-symlink-review-p_yxc2uw/`: pending publication and preexisting temporary live symlink from the recovery failure.
- Probe drivers: `/private/tmp/publisher-review-probes.py` and `/private/tmp/publisher-review-device.py`. These are review artifacts, not repository tests.

The reproduction descriptions above remain sufficient if temporary files are removed.

## Scope and remaining coverage gaps

The review covered the wrapper and CLI; edition schema and semantic validation; title configuration; web generation and templates; CSS and shared HTML helpers; device selection, measurement, capture, and PNG conversion; hashing, manifests, storage, activation, recovery, receipts, retention; and the existing tests and operational documentation. Generated types, dependency declarations, font-lock tests, and the bundled launchd examples were also inspected. Dependency internals were not audited.

The current suite gives useful evidence for deterministic builds, escaping, schema rejection, font assets, device dimensions and quantization, normal publication, the three explicit crash hooks, and retention. Its largest omissions are the journal transitions between those hooks, release-wide link/integrity checks, malformed CLI arguments, and adversarial combinations of otherwise valid fit inputs.

Further coverage worth adding after the confirmed findings are addressed:

- Test source expansion and stable column membership in actual desktop browsers, including Safari, plus the mobile breakpoint. Current column tests mainly inspect assignments and generated markup; this review did not run a Safari visual session.
- Exercise device restoration rollback and the candidate-budget boundary after a fitting layout has already been found. This review does not claim an additional confirmed bug in those paths.
- Test real process termination around every durable filesystem transition. Existing injected exceptions execute `finally` cleanup, unlike abrupt termination; documentation that a pre-intent crash leaves nothing behind is stronger than those tests establish.
- Define and test timeout/cleanup behavior for browser initialization and external build/conversion processes. The code has a navigation timeout but not an overall deadline covering every subprocess and settling step.
- Clarify or remove the stale `publisher/config/launchd/` examples: several contain empty schedule integers and combined argument strings. The documented active installation source is `editorial/config/launchd/`, so these are not counted as a confirmed production scheduling defect.

No live deployment, serving-layer behavior, external dependency vulnerability audit, exhaustive accessibility review, or filesystem power-loss durability test was performed. Recommendations are based on the checked-in implementation, passing local suite, and isolated reproductions—not an assertion that the deployed site is currently suffering every listed failure.

## Disposition, 30 September 2026

- **8** fixed: every action now declares its options (`src/cli/options.ts`); an unknown option, a
  repeated one, a value option without a value, a flag given a value, or a stray positional is a
  `usage_error` with exit 2 before anything runs. An error without a type is now reported as
  `internal_error` with exit 1, not as a usage error.
- **1** fixed: `recordActivation` clears the pending intent on the existing-record path too, after
  checking the record describes the same manifest and edition.
- **2** fixed: `swapLive` replaces its own leftover temporary link (a symlink at the run-owned name)
  before renaming; anything else at that path is a `publish_conflict`.
- **4** fixed: `verify` and `receipt` compare the manifest's digest with the activation record before
  trusting its inventory, and fail with `bundle_integrity_failed` on a mismatch.
- **3** recorded on the roadmap under the staging paper, to be built and rehearsed there.
- **5, 6, 7** left as they are: the device path is skipped by every scheduled run and is expected to be
  replaced; revisit if it returns.

Regression tests for 8, 1, 2 and 4 were written first and watched failing; the full check passes.
