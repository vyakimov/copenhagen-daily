# Desk operations

## The schedule

`config/ai.copenhagen-daily.edition.plist` is the launchd job for the Mac: copy it to
`~/Library/LaunchAgents/`, replace `REPO`, and load it. It runs `edit_news.sh run` a few minutes after
the policy's cutoff. On a server, the same command under cron. Do not install scheduler entries
automatically. Block 1's five-minute collector must already be scheduled; the run polls once more
before exporting so the window is current to the minute.

## What a run does

Collect, export the window, read memory, the editor session, the checker session, strikes, preflight,
publish, receipt, threads, commit. The run publishes the web edition only: block 3 is told to skip
the device page, and the desk makes no device decisions. On the final check a story that no longer
stands falls to a headline, and a struck headline is replaced by the primary source's own title. Each phase appends to `runs/<id>/status.json`, so `status`
says where a run is or where it stopped. The sessions are bounded by `limits` in `policy.yaml`, in
minutes and in turns; a limit hit stops the run and leaves the last activated edition in place. The
editor session may run only `check-clusters`, `score`, and `build` through the wrapper, has no web
tools and no MCP servers, and a change it makes anywhere in the repository outside its run directory
stops the run before `publish`.

## When a run fails

Read `runs/<id>/status.json`: `failure.phase` and `failure.type` say which step and why, and
`sessions/` holds each session's summary. Then:

- `editor_timeout`, `checker_timeout`, `run_timeout`: the session ran past its wall clock. Read the
  run directory for what it managed; the phase files are resumable. Run again with the same edition
  id and the runner continues from the first missing file.
- `contract_invalid`, `spec_invalid`: the editor wrote something block 3 would refuse. The details name
  the pointer. Fix the spec by hand and run `build`, or run again.
- `verdicts_invalid`: the checker's verdicts do not cover the check input sentence for sentence, or
  name a different edition. The details list the missing and unknown addresses. Run again; the check
  phase reruns the checker.
- `stray_edits`: a session wrote outside the run directory. The details name the paths. Read the
  diff, revert what should not be there, and run again; nothing was published.
- `internal_error`: the runner itself raised. The details carry the traceback. Fix, then run again.
- `lock_busy` from block 1 or block 3: another process holds a lock. Wait, then run again. The same
  type from block 2 means another `run` is in progress; `editorial/var/run.lock` names it.
- `not_activated`: `publish` returned but no activation exists. Run block 3's `recover`, then
  `receipt`; never generate a different edition to escape it.
- A failure in `receipt`, `threads`, or `archive` after an activated publish is not resumed by a
  rerun; the rerun would re-enter `publish` and block 3 would refuse the duplicate. Finish those
  steps by hand: block 3's `receipt`, then commit the run directory.

A published edition id is never rerun; the next edition corrects it.

## Rehearsing without publishing

`edit_news.sh run --dry-run` does everything up to `publish --dry-run --skip-device`, which assembles and removes a
release under the publish root, and skips the receipt, the thread registry, and the commit. Use it
after changing the handbook, the policy, or a skill.
