# Scheduling

Collection runs under macOS launchd. The job definition is
`editorial/config/launchd/ai.copenhagen-daily.collect.plist` at the repository
root, label `ai.copenhagen-daily.collect`. It runs
`<repository>/ingest/gather_news.sh collect --once`
through `/bin/sh -c` with `StartInterval` 900, so a poll starts every fifteen
minutes. Stdout and stderr go to
`~/Library/Logs/copenhagen-daily/collect.stdout.log` and
`collect.stderr.log`. The wrapper resolves its own repository and `.venv`, so
the job needs no `cd`, `uv`, or activated environment; the plist sets only
`PATH` and `HOME`.

Install or refresh the job with `launchctl bootstrap gui/$(id -u) <plist>` and
remove it with `launchctl bootout gui/$(id -u)/ai.copenhagen-daily.collect`. Do
not install scheduler entries from code or tests.

Overlapping runs are harmless: a second collector fails fast with `lock_busy`
on the process lock. `export` waits up to 90 seconds for that lock instead, so
an export started during a poll completes after the poll commits.

`poll_interval_seconds` in `config/sources.yaml` is validated but read by no
code; the interval lives only in the plist. There is no cron entry.

There is no live publisher check to schedule: `./gather_news.sh live-contracts`
returns `status: disabled` and does not constitute a check.
