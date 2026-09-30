# Desk operations

## The schedule

The Mac is the newsroom; AWS is delivery only. Five launchd jobs in `config/launchd/` run everything,
with logs under `~/Library/Logs/copenhagen-daily/`:

| Job | When | Command |
|---|---|---|
| `ai.copenhagen-daily.collect` | every fifteen minutes | block 1 `collect --once` |
| `ai.copenhagen-daily.edition` | 05:30 local | `edit_news.sh run` |
| `ai.copenhagen-daily.verify` | 06:00 local | `edit_news.sh verify-live --fix --notify`: checks the live site against the newsroom's copy, delivers again if that is the remedy, and posts the verdict either way |
| `ai.copenhagen-daily.retry` | 07:30 local | `edit_news.sh run --retry`: runs only if the morning edition has not already succeeded, resuming a failed run from its first missing file |
| `ai.copenhagen-daily.freshness` | 09:00 local | `edit_news.sh freshness --notify`: fails and notifies when the latest activated edition is older than `max_edition_age_hours` |

Install them once:

```sh
for f in editorial/config/launchd/*.plist; do cp "$f" ~/Library/LaunchAgents/; launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$(basename "$f"); done
launchctl list | grep copenhagen
```

The repository lives under `~/Documents`, which macOS protects from background jobs, so each job runs
its command through `/bin/sh`, which forks the wrapper and stays its parent. Grant Full Disk Access to
`/bin/sh` once (System Settings, Privacy & Security, Full Disk Access, the plus button, then
Shift-Command-G and `/bin/sh`), and every process the job starts inherits it. Without that grant the
job's stderr log says `Operation not permitted`. To stop one: `launchctl bootout gui/$(id -u)/ai.copenhagen-daily.edition`. launchd runs a missed
calendar job when the Mac wakes, so a Mac Studio asleep at 05:30 runs the edition late rather than losing it; keep it set to never sleep.

The jobs carry their own `PATH`, and its order matters: `/opt/homebrew/bin` comes before `~/.local/bin`
because other tools drop their own `node` there (Hermes keeps a Node 22 in it), and block 3 needs
Homebrew's Node 26. A `dependency_missing` failure naming a Node version means that order was lost.

## Delivery

After an activated publish the run syncs block 3's `live/` directory to the bucket named in
`config/desk.yaml` under `delivery` and invalidates the CloudFront distribution, through the AWS CLI
and the named profile. That profile is `copenhagen-daily-deliver`, an IAM user whose only rights are
listing and writing the one bucket and invalidating the one distribution; its key lives in
`~/.aws/credentials` and never needs a browser, which is what lets the launchd job deliver. The SSO
profile `copenhagen-daily` is for a person at the keyboard. With no bucket configured the phase is skipped. `edit_news.sh deliver` does the
same by hand, for example after a manual `recover`. The site is served unlisted: every page carries a
`noindex` meta tag and the release root has a `robots.txt` that disallows everything; CloudFront
should add an `X-Robots-Tag: noindex` header for files that are not HTML.

## Looking before publishing

Block 3's `preview` builds any edition contract into a scratch site and serves it on the loopback
interface, with the archive and prev/next navigation taken from the real publish root, and writes
nothing to the store:

```sh
publisher/publish_news.sh preview --edition editorial/runs/<id>/edition-checked.json --publish-root publisher/var/evaluation/site
```

The envelope names the URL; stop it with Ctrl-C. `--output DIR` writes the site instead of serving it.
Use it to look at a run's copy before a publish, and to see a layout change on a real edition before
the next morning's release carries it.

## Checking the site from outside

`verify-live` reads `live/latest.json`, the front page, and the edition's manifest from the site named
by `delivery.site_url` and compares them byte for byte with the newsroom's live tree, then fetches the
stylesheet the page links and looks for the `x-robots-tag` header. The verdict is one state:

- `ok`: everything matches and today's edition is up.
- `not_delivered`: the site is behind the newsroom, or the files differ. Delivering again is the
  whole remedy; `--fix` does it and checks again.
- `broken`: the stylesheet is missing (delivering again fixes it) or the robots header is gone (the
  CloudFront response function; not fixed automatically).
- `no_edition_today` / `run_in_progress`: yesterday's paper is correctly on the site and today's is
  not; the second form means a run holds the lock. Nothing is done: the 07:30 retry covers a failed
  run, and the notification says so.
- `unreachable` / `no_local_edition`: the site or the publish root could not be read.

The action never edits anything; its one fix is the deterministic delivery step. Anything else is a
message to the owner.

## Being told

A run that fails notifies the owner once, the freshness job notifies when no edition is fresh, and the
verify job posts its verdict every morning, good or bad, so silence itself is a signal.
`notify.command` in `config/desk.yaml` names a script that receives the subject as its argument and
the body on stdin. Without one, `var/discord.env` posts to a Discord channel: in the channel's
settings choose Integrations, Webhooks, New Webhook, copy the URL, and paste its two parts:

```
DISCORD_WEBHOOK_ID=123456789012345678
DISCORD_WEBHOOK_TOKEN=the long token after the id
```

Regenerate the webhook in Discord if the token ever leaks; nothing else changes. Without that file,
`var/smtp.env` sends an email:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=an app password
MAIL_FROM=you@gmail.com
MAIL_TO=you@gmail.com
```

With neither, a macOS notification appears and the message goes to the job's stderr log.

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
- `stray_edits`: a session wrote outside the run directory. The working tree is compared before and
  after each session, so only what the session changed counts; your own uncommitted work elsewhere in
  the repository does not block the paper. The details name the paths. Read the diff, revert what
  should not be there, and run again; nothing was published.
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
release under the publish root, and skips the receipt, the thread registry, delivery, and the commit. Use it
after changing the handbook, the policy, or a skill.
