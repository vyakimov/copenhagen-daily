# Block 2 code review

Reviewed 30 September 2026, against commit `b3fde9e3b2ed976aa255173062a32da81c4c30d9` and the clean working tree present at the start of the review.

## Conclusion

Block 2 has a clear decomposition, useful audit artifacts, and a strong baseline of deterministic tests. Its normal execution path is well covered. However, I would not consider its unattended operation sufficiently reliable yet: the evidence boundary is mutable, session edit detection misses changes to existing work, and several retry paths cannot recover without manual intervention. The automatic archive can also commit unrelated staged changes.

This review identifies **12 findings: 6 P1 and 6 P2**. P1 means fix before relying on unattended operation; P2 means a concrete correctness gap to address subsequently. No code, configuration, existing tests, or published artifacts were changed. This report is the only repository addition.

## Scope and verification

Reviewed all Python production modules in `editorial/src/news_editorial/`, the wrapper, dependency declarations, schemas, policy, desk configuration, launchd definitions, editor/checker instructions, operations documentation, and the test suite's coverage. Cross-checked the relevant ingest export filter and publisher duplicate-publication handling. The editorial skills were reviewed as application inputs, not invoked to create an edition.

Executed the existing suite using the provisioned Python environment because the wrapper has no test action:

```sh
cd editorial
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider
```

**Result: 132 passed in 6.05 seconds.** Additional isolated probes used temporary directories, existing test fixtures/fakes, and, for the archive finding, a separate temporary Git repository. The standalone verdict probe used `editorial/edit_news.sh`. No model, AWS, notification, deployment, or live-site calls were made. These probes establish deterministic behavior, not the quality of a real model's editorial decisions.

## Findings

### 1. [P1] The editor can change the evidence subsequently given to the checker

Locations: `editorial/src/news_editorial/run.py:435–443,515–528`; `editorial/src/news_editorial/verdicts.py:240–251`.

The session guard permits every write within the run directory. That includes `window.json`, the retained bundle, and other runner-owned inputs. After the editor finishes, `_check_once()` rereads `window.json` and constructs the checker's evidence from it. No comparison against the pre-session bytes or verified bundle is performed. Contract validation checks shape and references, not whether this evidence is still the frozen source material. Missing article identities even fall back to the edition's `original_title`.

**Confirmed:** a fake editor replaced descriptions in `window.json` with an invented sentinel while producing an otherwise valid edition. The checker received the invented descriptions and the fake-backed run reached `published`. This does not demonstrate that a real checker would approve any particular invention; it demonstrates that its supposed independent evidence can be supplied by the writer.

**Fix:** distinguish model-owned outputs from runner-owned inputs. Keep a verified evidence snapshot outside the writable session area, or verify frozen digests after every session and reconstruct checker evidence from that snapshot. Reject missing source identities and mismatched source metadata. Add a test that modifies an input inside the run directory and requires failure before checking/publishing.

### 2. [P1] Stray-edit detection ignores changes to already-dirty files and ignored state

Locations: `editorial/src/news_editorial/run.py:173–176,515–528`.

`_session()` compares sets of dirty path names, not before/after content. A path already dirty before the session is exempt even when the session overwrites it completely. `git status` also omits ignored files, including other blocks' runtime state. The post-session check is skipped entirely when the session raises.

**Confirmed:** a file outside the run directory started with owner changes and appeared in the baseline dirty-path list. The fake editor replaced its contents; the run still reached `published`. The existing test for preserving the owner's work only keeps the dirty path list constant and does not exercise a content change.

**Impact:** the stated write boundary does not protect work in progress, and the paper can proceed after an out-of-scope modification.

**Fix:** isolate session writes or compare content/state snapshots, including pre-existing modifications and relevant ignored files. Perform the comparison in failure handling as well. Do not solve this by requiring the owner to discard unrelated work.

### 3. [P1] Archiving commits the entire shared Git index

Location: `editorial/src/news_editorial/run.py:632–638`.

The runner stages the run files and calls plain `git commit`. That commits every staged path, including unrelated work the owner staged before the scheduled run. Restricting `git add` does not restrict the subsequent commit.

**Confirmed with real Git in a temporary repository:** staged `unrelated.txt`, called `_archive()`, and inspected the resulting commit. It included `unrelated.txt` under the edition archive commit message.

**Fix:** commit only the intended run paths using an isolated index or another approach that preserves the existing index. Test with both unrelated staged changes and partially staged files. The real repository's index was not changed by this review.

### 4. [P1] Invalid checker output is cached and makes retries fail indefinitely

Locations: `editorial/src/news_editorial/run.py:424–455`.

`_verdicts_on_disk_for()` only checks that `verdicts.json` exists and the previous check input equals the current input. It never checks that the cached verdicts passed schema, identity, or coverage validation. A malformed, incomplete, or wrong-edition response therefore prevents the checker from being invoked again on the same input. This contradicts the operations guidance that a rerun after `verdicts_invalid` reruns the check phase.

**Confirmed:** the first checker omitted one story and failed with `verdicts_invalid`. A retry with a corrected checker failed with the same error; total checker invocations remained **one**.

**Fix:** reuse only a validated successful checkpoint tied to an input digest and checker round. Invalidate unsuccessful or truncated output and request a new check. Apply the same principle to edition resumption: currently the mere presence of `edition.json` and `NOTES.md` skips the editor even when the edition is invalid.

### 5. [P1] Failures after activation cannot resume the remaining delivery work

Locations: `editorial/src/news_editorial/run.py:286–295,310–327,497–513,596–602`; supporting behavior in `publisher/src/publish/store.ts:501–517`.

Delivery, thread, receipt, or archive failures mark the whole run `failed`. A retry resets status and starts the phase sequence again, including `publish`. Block 3 correctly rejects an already stored edition with `bundle_exists` or `publish_conflict`, so the retry cannot reach the unfinished delivery/archive work. Receipt/thread/archive recovery limitations are partly documented, but delivery has the same problem and the scheduled retry does not repair it.

**Confirmed:** simulated successful activation followed by a delivery exception. The retry failed in `publish` against a duplicate-refusing fake publisher and made **zero** calls to the now-working deliverer. The real publisher's source explicitly implements this duplicate refusal.

**Impact:** an edition can be activated locally yet remain undelivered after a temporary network failure. The separate verify job can help if it runs afterward, but it does not make this retry path resumable. The failure notification's claim that the previous edition remains activated is also wrong after this point.

**Fix:** persist and reconcile publication identity/receipt first on restart, then resume idempotent post-activation phases without republishing. Preserve the original failure history and distinguish local activation from external delivery in status and notifications.

### 6. [P1] Session timeouts leave descendant processes running

Locations: `editorial/src/news_editorial/run.py:89–95`; analogous subprocess handling in `editorial/src/news_editorial/blocks.py:24–28`.

`subprocess.run(..., timeout=...)` terminates the direct child but provides no process-group cleanup here. The editor can launch wrapper commands and delegated work. Those descendants can continue writing after the runner records a timeout and releases its lock. This undermines the wall-clock limit and allows a subsequent run to overlap outstanding work.

**Confirmed:** a temporary parent process launched a child that would write a marker after 0.4 seconds. `_headless()` timed out the parent after 0.1 seconds and returned `editor_timeout`; the child subsequently wrote the marker. No model or production subprocess was involved.

**Fix:** launch managed work in a dedicated process group/session, terminate the group on timeout, escalate to killing it if needed, and wait for cleanup before releasing the run lock. Test descendants, not just a sleeping parent CLI.

### 7. [P2] Late discoveries and old material corrections never enter the candidate window

Locations: `editorial/src/news_editorial/run.py:377–398`; `editorial/src/news_editorial/actions.py:79–92`; `ingest/src/news_ingest/export.py:57–67`.

Both window paths request only `export --since <cutoff minus 72 hours> --until <cutoff>`. The producer filters exclusively on `published_at`. An article published four days ago but first observed today, or an older article corrected today, is absent before Block 2 computes `newly_observed`. Attaching that flag to already-admitted rows cannot admit the missing article.

**Evidence:** traced the wrapper arguments to the producer's SQL predicate `published_at>=? AND published_at<?`. No observation/content-change supplement is requested. This conflicts with the explicit late-arrival and correction exceptions in `plans/news-editorial-architecture-plan.md:348` and the build plan's window description.

**Fix:** combine the publication window with a bounded observation/change input, deduplicate by article identity/revision, and retain provenance for every input. Respect the producer's changed-since boundary limitations rather than assuming that export is already a bounded snapshot. Test an old newly discovered article and an old corrected article.

### 8. [P2] Duplicate verdict entries can strike the wrong sentences

Locations: `editorial/src/news_editorial/verdicts.py:201–208,104–108`; `editorial/contracts/verdicts.v1.schema.json`.

Coverage validation converts verdict addresses into a set, losing duplicate information. The schema permits duplicate story entries. `apply_verdicts()` then processes those entries sequentially against a story it has already mutated, so the second entry's sentence and paragraph indexes no longer refer to the original input.

**Confirmed:** a paragraph contained “First fact. Second fact. Third fact. Fourth fact.” Two duplicate story entries each struck original sentence index 1. Coverage reported no missing or unknown addresses, but the result was “First fact. Fourth fact.” The supported third sentence was removed as well.

**Fix:** require unique story IDs and exactly one verdict per original address before any mutation. Reject duplicate addresses even when their verdicts agree. A `Counter` or explicit uniqueness validation can supplement the existing missing/unknown checks.

### 9. [P2] The standalone verdict action writes a checked edition without checking coverage

Location: `editorial/src/news_editorial/actions.py:219–240`.

The runner enforces sentence coverage, but the public `apply-verdicts` action only validates edition identity and the verdict schema before applying strikes. Empty or partial verdicts are schema-valid; unmentioned copy survives and the action writes `edition-checked.json` successfully.

**Confirmed through the actual wrapper:** supplied the golden edition and `{"schema_version":1,"edition_id":"2026-09-15-morning","stories":[]}`. `apply-verdicts --final` exited **0**, reported **zero checked stories**, and wrote an unchanged checked edition.

**Fix:** enforce the same complete, unique address coverage in both paths. If a partial-strike utility is useful, make it explicitly separate and avoid presenting its output as a completed check. This finding concerns the manual action; the normal runner does reject missing addresses.

### 10. [P2] Send-back revisions can change the edition identity before publication

Location: `editorial/src/news_editorial/run.py:476–481`; compare the initial identity check at `421–422`.

After a send-back, the runner validates the revised contract but does not repeat the comparison between its edition ID and `self.edition_id`. The checker is asked about the revised ID, so matching verdicts do not catch this. Publication uses the revised file, while receipt lookup and status still use the original run ID.

**Confirmed with fakes:** a send-back changed `2026-09-15-morning` to `2026-09-15-evening`. The revised document reached the fake publisher while runner status retained the morning ID. The fake receipt let the probe finish; a real receipt lookup would instead expose the mismatch after publication, when it is already too late to preserve the original identity.

**Fix:** validate frozen edition metadata after every revision and immediately before publication. Enforce the send-back constraint that only named stories may change. Add a test requiring rejection before invoking the publisher.

### 11. [P2] One fresh feed suppresses collection for every stale feed

Location: `editorial/src/news_editorial/run.py:355–361`.

The collection shortcut takes the maximum `last_successful_poll_at` across feeds. Consequently, one recent success is treated as evidence that the whole collector inventory is recent. An interrupted collection, selective poll, or partially stale inventory can suppress a useful catch-up poll for all other feeds. Later coverage classification uses failure counters and timestamp presence, not freshness, so an old successful poll can still be called `checked`.

**Confirmed:** health contained one feed last successfully polled five minutes ago and another last polled fourteen days ago. `_collect()` skipped with `reason: recent_poll` and did not invoke collection.

**Fix:** use a completed collection-run checkpoint or assess the freshness of the required feed inventory individually, accounting for failed checks separately from successful polls. Test mixed fresh/stale feeds and interrupted collection.

### 12. [P2] Live verification accepts a mismatching latest pointer

Location: `editorial/src/news_editorial/verify.py:80–92`.

The operations guide promises byte-for-byte comparison of `latest.json`, but the code compares only `web.edition_id`. Incorrect dates, device pointers, statuses, and other pointer fields pass while the report says the latest pointer matches. Matching manifest and front-page bytes do not verify those independent fields.

**Confirmed:** changed the remote web date to `1900-01-01` and added a stale device edition pointer, while preserving `web.edition_id`. `verify_live()` returned `state: ok`.

**Fix:** compare the complete pointer bytes as documented, or validate and compare all relevant fields with an explicitly stated semantic policy. Add same-edition/different-pointer cases, including device state.

## Additional observations and review limits

- The policy's 24-story ceiling is only a ranking annotation: `build` does not consume that limit, and the spec permits 64 stories. The checker turn limit is passed to the Claude branch but is unused in the Codex branch. These are gaps between configured limits and deterministic enforcement; word-budget guidance is explicitly advisory to the checker.
- Status and phase JSON are written in place. A process or machine failure during a write can leave truncated files that presence-based resumption treats as checkpoints. Atomic replacement and validated phase markers would complement findings 4 and 5. The thread registry already uses temporary-file replacement.
- Recovery also resets the send-back counter: `_check()` starts again with `final=False` rather than persisting whether the saved verdicts came from the final round. Interrupted finalization can therefore grant another rewrite beyond the intended per-edition allowance.
- Runtime behavior and documentation have drifted. `desk.yaml` enables device rendering and AWS delivery, while sections of `OPERATIONS.md`, the runner module docstring, and the spec's device descriptions still say runs skip the device or fields are inert. The root instruction that editorial has no publishing credentials also conflicts with the runner invoking the configured AWS delivery profile. The deterministic orchestrator/model-session distinction should be made explicit in the authoritative boundaries.
- Model CLI permission behavior, inherited user configuration, actual MCP availability, launchd installation, credentials, and live infrastructure were not exercised. Argument-construction tests alone do not prove effective tool isolation. This report does not claim they do.
- Positive coverage includes source resolution, bundle hash checks for normal producer manifests, citation membership, the shared contract rejection corpus, ranking terms, basic lock contention, headline fallback, and the standard single send-back path. The missing tests are concentrated around trust boundaries, duplicate/partial outputs, and interrupted/post-activation recovery.

## Suggested repair order

1. Protect frozen evidence and owner files; isolate the archive commit (findings 1–3).
2. Make validated checkpoints, activation-aware recovery, and subprocess cleanup reliable (4–6).
3. Unify verdict validation and preserve edition identity across revisions (8–10).
4. Restore candidate/collection completeness and verify the entire live pointer (7, 11–12).

Each fix should add the specific failure case described above to the regression suite. A subsequent end-to-end rehearsal should interrupt a check and fail delivery after activation, then demonstrate recovery without modifying evidence, repeating publication, or committing unrelated work.

## Disposition, 30 September 2026

- **1–4, 6, 8–12** fixed the same day (commit "Harden the desk's trust boundary and retry paths"),
  each with the review's failure case as a regression test: runner-owned inputs are hashed around
  every session; the stray guard compares content and runs on session failure; the archive commits
  only the run's paths; invalid cached verdicts and editions are not reused; sessions and wrappers
  run in their own process group; duplicate verdict addresses, the manual apply action's coverage, the
  send-back's identity and scope, the collect shortcut, and the live pointer comparison.
- **5** fixed next: the run reconciles with block 3's receipt first and, when the edition is already
  activated, resumes from the step after the publish; earlier failures are kept; the notification
  distinguishes local activation from delivery; a store needing recovery stops the run before any session.
- **7** designed on the roadmap ("Late discoveries in the candidate window") as a block 1 export input.
- The documentation drift noted under additional observations is corrected; the send-back counter on
  resume and in-place status writes are noted but not changed.
