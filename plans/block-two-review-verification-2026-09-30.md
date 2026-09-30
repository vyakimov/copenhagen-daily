# Block 2 review: verification of fixes

Verified 30 September 2026 at commit `d32dd35`, including fixes in `5bc2459` and `ffd27cc`. The working tree was clean at the start. This report is the only repository change made during verification.

## Conclusion

**Not all findings are resolved: seven are verified fixed for their reported failure cases, four are partially fixed, and one is explicitly deferred.** The four remaining implementation gaps retain the original P1 priority. The changes improve the normal paths, but the disposition in the original report overstates closure of findings 1, 2, 4, and 6.

The complete editorial suite passes: **146 passed in 9.15 seconds**, up from 132 tests. Independent temporary-directory probes reproduced the remaining failures below. No models, live publishing, delivery, notifications, or credentials were exercised, and no production code or tests were modified.

## Remaining findings

### [P1] 1. Rejected evidence changes become trusted on retry

Locations: `editorial/src/news_editorial/run.py:430–433,605–610,630–647`.

The new input digests correctly detect a change during a session. However, the digests exist only for that session, and the changed files remain on disk after `input_modified`. The next run treats the existing `window.json` as a completed checkpoint and skips reconstruction/verification. If the failed editor already wrote a valid edition and notes, the editor is also skipped. The checker then receives the evidence rejected by the previous run.

Independent reproduction:

1. Run with an editor fake that produces a valid edition and notes, then replaces window descriptions with `POISONED_REVIEW_EVIDENCE`.
2. Confirm the first run fails with `input_modified` before checking.
3. Retry using the normal editor/checker fakes, capturing the checker input.
4. The retry reaches the fake publisher and reports `published`; the checker input contains the poisoned descriptions.

Observed output:

```text
evidence_retry input_modified published checker_saw_poison True
```

The existing new test stops after step 2, so it misses this recovery path. This proves the provenance failure, not that a real model would approve a particular invented sentence.

**Required closure:** retain an authoritative evidence identity across attempts, or quarantine/invalidate a run whose protected inputs changed. Reconstruct from a independently verified retained snapshot and invalidate dependent artifacts before resuming. Do not simply accept the modified bytes as the new baseline. Add the two-attempt regression above.

### [P1] 2. The edit guard misses reversions and ignored runtime files

Locations: `editorial/src/news_editorial/run.py:181–184,613–620,637–638`.

Hashing already-dirty files fixes overwrites that leave them dirty. Two important cases remain:

- The comparison iterates only `tree_after`. If the session overwrites an unstaged owner edit with the committed contents, the path disappears from `git status`; the owner's edit is lost, and no violation is detected.
- `_tree_digests()` still enumerates the existing Git-status path list. Ignored runtime files outside the run directory never enter either snapshot, so changing them is still invisible.

Independent reproduction used a real temporary Git repository, not a synthetic dirty-path list. A tracked file was committed, modified with owner work, and restored to committed contents inside `_session()`. A second probe changed an ignored `state/runtime.json` outside the run directory. Both calls were accepted:

```text
dirty_reverted_to_clean accepted
ignored_state_change accepted
```

The failure wrapper also catches only `RunFailure`; unexpected exceptions still skip the comparison. The principal demonstrated defects are the two snapshot gaps above.

**Required closure:** compare the union of before/after paths and include protected ignored state, or enforce write isolation independently of Git. Evaluate the guard in robust cleanup handling. Add real-Git tests for dirty-to-clean reversion and ignored state modification.

### [P1] 4. Complete but schema-invalid verdicts are still reused indefinitely

Location: `editorial/src/news_editorial/run.py:494–509`.

The cache check now validates input equality, edition identity, and address coverage. It does not call the verdict schema validator. Therefore a document covering every address but containing an invalid verdict value or unexpected field is reused, only to fail later in `apply_verdicts()`.

Independent reproduction:

1. Let the checker produce complete verdicts, then change one verdict to `"maybe"`.
2. The first run fails with `verdicts_invalid`.
3. Retry with the normal checker capable of producing valid verdicts.
4. The retry also fails with `verdicts_invalid`; the checker was invoked only once across both attempts.

```text
schema_invalid_retry verdicts_invalid verdicts_invalid checker_calls 1
```

The newly added test covers missing story addresses, which now recover correctly; it does not cover schema-invalid output with complete coverage.

**Required closure:** run full schema validation on cached verdicts before accepting the checkpoint, in addition to identity and unique coverage validation. Test an invalid enum value and an unexpected property.

### [P1] 6. Timeout cleanup stops when the parent exits, even if descendants survive

Location: `editorial/src/news_editorial/blocks.py:37–47`.

Starting a dedicated process group fixes the straightforward sleeping-child case. `_end_group()` sends `SIGTERM` to the group, but then waits only for the direct child and returns as soon as it exits. A descendant that ignores or delays handling `SIGTERM` never receives the intended `SIGKILL` escalation if its parent exits promptly.

Independent reproduction launched a temporary parent and a child in the same process group. The child installed a `SIGTERM`-ignore handler and signalled readiness, then scheduled a marker write. After `_headless()` timed out the parent, the child wrote its marker:

```text
timeout editor_timeout
term_ignoring_child_survived True
```

The child was short-lived and finished during the probe. No production process was involved.

**Required closure:** distinguish parent exit from process-group termination. Ensure remaining group members receive escalation after the grace period, and clean up the parent/pipes before returning. Add a test where the parent exits on TERM but a child does not.

## Disposition of all 12 original findings

“Verified fixed” means the reported failure case is addressed by the current code and passing regression coverage; it is not a claim that all surrounding behavior is proven correct.

| Original finding | Verification | Evidence |
|---|---|---|
| 1. Mutable checker evidence | **Partial** | Immediate mutation is detected; retry trusts the rejected on-disk evidence. Independently reproduced above. |
| 2. Stray edits | **Partial** | Dirty-content overwrite and `RunFailure` tests pass; dirty-to-clean reversions and ignored state remain invisible. |
| 3. Unrelated staged work committed | **Verified fixed** | Archive now uses `git commit --only` with run paths. Real-Git regression confirms unrelated staged work stays staged and out of the archive commit. |
| 4. Invalid verdict cache | **Partial** | Missing coverage is retried successfully; full-coverage schema-invalid output remains cached. |
| 5. Post-activation recovery | **Verified fixed for the reported failure** | Receipt reconciliation skips publication/model phases after activation; the delivery-failure retry test reaches delivery without publishing twice and retains the previous failure. Publisher receipt behavior was cross-checked in source. |
| 6. Surviving subprocesses | **Partial** | Ordinary children receive TERM, but cleanup does not finish off a surviving descendant after parent exit. |
| 7. Late discoveries/corrections | **Deferred, not fixed** | Publication-window-only export remains. The limitation is explicitly recorded in the roadmap and disposition. |
| 8. Duplicate verdicts | **Verified fixed at runner/action boundaries** | Coverage validation now reports duplicate story IDs and addresses; callers reject them before applying strikes. |
| 9. Incomplete manual verdict application | **Verified fixed** | The public action now requires window evidence and complete unique address coverage before writing the checked edition; its regression passes. |
| 10. Send-back edition identity | **Verified fixed for the reported failure** | Revised ID is compared to the runner ID before publication. Tests reject renaming and changes to existing untouched stories. |
| 11. One fresh feed skips collection | **Verified fixed for the reported failure** | Freshness now uses the oldest successful poll among healthy feeds and requires timestamps for all of them. Mixed fresh/stale regression passes. |
| 12. Incorrect live pointer accepted | **Verified fixed** | Verification compares complete pointer bytes; same-edition pointer differences are reported as undelivered. |

The pre-existing additional observations about in-place status writes and resetting the send-back counter are explicitly deferred in the roadmap. The story-count ceiling and Codex checker turn-limit enforcement were not changed by these commits. Documentation clarifying deterministic delivery versus model sessions does not itself establish effective credential isolation; real CLI permissions and inherited configuration remain outside this verification.

## Validation performed

- Reviewed the full production-code diff from `b3fde9e` to `d32dd35`, the added tests, and relevant publisher receipt semantics.
- Ran `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider` from `editorial/`: **146 passed**.
- Ran independent probes using the existing runner fakes for evidence retry and schema-invalid cache behavior.
- Used a separate temporary Git repository for actual status enumeration in the reversion/ignored-state probes.
- Used short-lived Python subprocesses for the TERM-resistant descendant probe.
- No live edition or operational state was modified. Only this verification report was added.

The immediate next step is to close the four P1 gaps with the specific regression cases above, then rerun verification. Finding 7 can remain explicitly deferred if that product limitation is accepted, but should not be counted as resolved.

## Closure, 30 September 2026 (later)

- **1.** The runner records digests of its inputs (`inputs.json`) whenever it writes them. A session
  that changes them, or a change found at the start of the next run (new `inputs` phase), quarantines
  the inputs and every model output into `quarantine-<time>/` and fails `input_modified`; the retry
  rebuilds from the verified source. The two-attempt case is a test, with a check that the checker's
  input carries none of the poisoned text.
- **2.** The guard compares the union of before and after paths (a reversion to the committed text is
  caught), includes the thread registry as protected state outside git, and runs on any exception.
  Real-git tests cover the reversion and the ignored-state change.
- **4.** Cached verdicts must pass the schema as well as identity and coverage before reuse.
- **6.** Group termination watches the group until it is empty, escalating to SIGKILL after the grace
  period whether or not the parent is gone; a TERM-ignoring descendant is the test.
- Block 1, from the documentation audit: a failed poll now counts against its feed
  (`consecutive_failures`, `last_error_json`) so `health` can report it; the export takes the
  collector's process lock while it reads and stamps `generated_at`, so a poll in flight cannot commit
  rows behind the cursor. Rebuild-applied repairs keep their historical change time by design and are
  therefore invisible to a changed-since export; this is recorded with the late-discoveries roadmap item.
