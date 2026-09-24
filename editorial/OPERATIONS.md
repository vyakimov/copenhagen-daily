# Desk operations

## The schedule

`config/ai.copenhagen-daily.edition.plist` is the launchd job for the Mac: copy it to
`~/Library/LaunchAgents/`, replace `REPO`, and load it. It runs `edit_news.sh run` a few minutes after
the policy's cutoff. On a server, the same command under cron. Do not install scheduler entries
automatically. Block 1's five-minute collector must already be scheduled; the run polls once more
before exporting so the window is current to the minute.

## What a run does

Collect, export the window, read memory, the editor session, the checker session, strikes, preflight,
fit, publish, receipt, threads, commit. Each phase appends to `runs/<id>/status.json`, so `status`
says where a run is or where it stopped. The sessions are bounded by `limits` in `policy.yaml`; a
limit hit stops the run and leaves the last activated edition in place.

## When a run fails

Read `runs/<id>/status.json`: `failure.phase` and `failure.type` say which step and why, and
`sessions/` holds each session's summary. Then:

- `editor_timeout`, `checker_timeout`, `run_timeout`: the session ran past its wall clock. Read the
  run directory for what it managed; the phase files are resumable. Run again with the same edition
  id and the runner continues from the first missing file.
- `contract_invalid`, `spec_invalid`: the editor wrote something block 3 would refuse. The details name
  the pointer. Fix the spec by hand and run `build`, or run again.
- `fit_unrepairable`: the device fit failed after the bounded editorial rounds. The web edition was
  not published either. Reduce the required set in `spec.json`, `build`, then run again.
- `lock_busy` from block 1 or block 3: another process holds a lock. Wait, then run again.
- `not_activated`: `publish` returned but no activation exists. Run block 3's `recover`, then
  `receipt`; never generate a different edition to escape it.

A published edition id is never rerun; the next edition corrects it.

## Rehearsing without publishing

`edit_news.sh run --dry-run` does everything up to `publish --dry-run`, which assembles and removes a
release under the publish root, and skips the receipt, the thread registry, and the commit. Use it
after changing the handbook, the policy, or a skill.
