# Desk operations

## The schedule

The Mac is the newsroom; AWS is delivery only. Five launchd jobs in `config/launchd/` run everything,
with logs under `~/Library/Logs/copenhagen-daily/`:

| Job | When | Command |
|---|---|---|
| `ai.copenhagen-daily.collect` | every fifteen minutes | block 1 `collect --once` |
| `ai.copenhagen-daily.edition` | 05:30 local | `edit_news.sh run` |
| `ai.copenhagen-daily.verify` | 06:00 local | `edit_news.sh verify-live --fix --notify`: checks the live site against the newsroom's copy, delivers again if that is the remedy, and posts the verdict either way |
| `ai.copenhagen-daily.retry` | 07:30 local | `edit_news.sh run --retry`: skips when today's run already ended as published, dry run, or skipped; otherwise resumes the failed run from its first missing file |
| `ai.copenhagen-daily.freshness` | 09:00 local | `edit_news.sh freshness --notify`: fails and notifies when the latest activated edition is older than `max_edition_age_hours` |

The files in `config/launchd/` are templates: `@REPO@` and `@HOME@` stand for this repository's path
and the login home. Install or reload them with:

```sh
editorial/config/launchd/install.sh
```

It renders each template into `~/Library/LaunchAgents/`, boots the label out if it is loaded, and
boots it back in.

The repository lives under `~/Documents`, which macOS protects from background jobs, so each job runs
its command through `/bin/sh`, which forks the wrapper and stays its parent. Grant Full Disk Access to
`/bin/sh` once (System Settings, Privacy & Security, Full Disk Access, the plus button, then
Shift-Command-G and `/bin/sh`), and every process the job starts inherits it. Without that grant the
job's stderr log says `Operation not permitted`. To stop one: `launchctl bootout gui/$(id -u)/ai.copenhagen-daily.edition`. launchd runs a missed
calendar job when the Mac wakes, so a Mac Studio asleep at 05:30 runs the edition late rather than losing it; keep it set to never sleep.

The jobs carry their own `PATH`, and its order matters: `/opt/homebrew/bin` comes before `~/.local/bin`
because other tools drop their own `node` there (one on this machine keeps a Node 22), and block 3 needs
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
adds an `X-Robots-Tag: noindex` header for files that are not HTML, and `verify-live` checks for it.

## The kitchen screen

With `device: true` in `config/desk.yaml`, every publish also fits and renders block 3's device page
from the same contract; the desk makes no device decisions. A device failure degrades the publish to
web-only and the web edition is unaffected. The newest page is always at
`https://copenhagen-daily.net/device/current.png`, which `deliver` syncs and invalidates with the rest
of the site; the screen's TRMNL Image Display plugin reads it from there. Block 3 needs its pinned Chromium (`publisher/OPERATIONS.md`) on the Mac.

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
by `delivery.site_url` and compares them byte for byte with the newsroom's live tree. The
`x-robots-tag` header is read from the `latest.json` response; the stylesheet the front page links is
fetched and must return HTTP 200 (its bytes are not compared). The verdict is one state:

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

## This deployment's names

`config/desk.yaml` is committed and holds the shape and the defaults. The names that belong to this
deployment alone, the bucket, the distribution id, the CLI profile, live in `var/desk.local.yaml`, which git ignores and which is laid over the committed file key
by key when the desk starts. Without it, delivery is skipped.

## The desk's own login

The Claude sessions need a claude.ai login. Under launchd the CLI reads it from the macOS keychain
entry, and that entry can lapse: on 2026-10-08 a refresh elsewhere rotated the refresh token, the
05:30 job's refresh was rejected, and the CLI blanked the entry, so the edition and its retry both
failed at the desk. To make the jobs independent of the keychain, mint a long-lived token at the
keyboard and keep it in `var/claude-oauth.env`, owner-readable only:

```sh
claude setup-token > editorial/var/claude-oauth.env
chmod 600 editorial/var/claude-oauth.env
```

The file holds the bare token, or `CLAUDE_CODE_OAUTH_TOKEN=...`. The runner passes it as
`CLAUDE_CODE_OAUTH_TOKEN` to the desk, writer, and Claude checker sessions and to nothing else; the
codex checker never sees it. The token expires a year after it is minted.

An API key in `var/claude-api-key.env` (the bare key, or `ANTHROPIC_API_KEY=...`, owner-readable
only) is the fallback. Every run tries the token first. When the token file is missing, or a session
fails to authenticate with the token, the run moves to the key and stays on it for the rest of that
run: the failed session is run once more on the key, both attempts are kept under `sessions/` (the
second one named `-api-key`), and `sessions/auth-fallback.json` records why and when. The owner is
notified the first time a run moves to the key, through the usual channel ("Being told"), because the
key is billed per token (a morning's sessions cost on the order of ten dollars) and the token needs
renewing; if that notification cannot be delivered, the text goes to the job's stderr log and the
fallback record remains. The next run tries the token again, so a renewed token takes effect on its
own. A session that fails for any other reason is not rerun on the key. With neither file the
sessions use the CLI's own login, which under launchd is the keychain entry.

To check the login the jobs will actually use, probe from launchd, not from a Claude Code shell: a
sandboxed shell cannot read the keychain and falls back to `~/.claude/.credentials.json`, so it can
look logged in while the jobs are not.

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

The phases, in order: `reconcile` (ask block 3 whether the edition is already activated), `inputs`
(verify the run's recorded inputs, see below), `collect`, `window`, `memory`, `editor` (the desk
session: clusters, ranking, selection, the log), `write` (one read-only session per story, a few at a
time, then the spec and the contract assembled by the runner), `check`
(the checker session and the strikes, with at most one send-back, which rewrites only the stories sent
back, each in its own session again), `preflight`, `publish`, `receipt`,
`threads`, `deliver`, `archive` (the commit). With `device: true` in `config/desk.yaml`,
as it is, the publish also renders the device page from the same contract; the desk makes no device
decisions. On the final check a story that no longer stands falls to a headline, and a struck
headline is replaced by the primary source's own title. Each phase appends to `runs/<id>/status.json`,
so `status` says where a run is or where it stopped. The sessions are bounded by `limits` in
`policy.yaml`: each by wall clock in minutes; `editor_turns` bounds the desk session, `writer_turns`
each writing session, and `checker_turns` the checker only when it is Claude, since the Codex checker
takes no turn bound; `writer_concurrency` says how many stories are written at once. A limit hit
stops the run and leaves the last activated edition in place. The desk session may run only
`check-clusters` and `score` through the wrapper, has no web tools and no MCP servers; a writing
session has the Read tool and nothing else; and a change any session makes anywhere in the repository
outside its run directory stops the run before `publish`.

The runner records what it writes for the sessions (`window.json`, `window.md`, `window-linked.md`,
`memory.json`, `feeds.json`, `check-input.json`, the writers' briefs and Wikipedia lookups under `stories/`, and the bundle)
as digests in `runs/<id>/inputs.json`. After every
session, and at the start of every run in the `inputs` phase, the files on disk must match that
record.

## When a run fails

Read `runs/<id>/status.json`: `failure.phase` and `failure.type` say which step and why, and
`sessions/` holds each session's summary. Then:

- `editor_timeout`, `writer_timeout`, `checker_timeout`, `run_timeout`: the session ran past its wall clock. Read the
  run directory for what it managed; the phase files are resumable. Run again with the same edition
  id and the runner continues from the first missing file.
- `selection_invalid`: the desk's `selection.json` is incomplete: no lead first, a story without a
  kicker or sources, a source not in the window, or no edition presentation and note. Nothing was
  written. Fix the selection by hand or run again.
- `contract_invalid`: the stories do not build into a valid edition, or the struck edition fails
  block 3's contract. A story whose copy was the problem has already been written once more with the
  problem in its brief. The details name the pointer. Run again.
- `editor_failed`, `writer_failed`, `checker_failed`: the session exited non-zero or reported an
  error, or a writer's answer was not usable copy twice; `sessions/` holds each record. Run again;
  stories already written are kept under `stories/` and only the missing ones are written.
  A record whose result starts with `Failed to authenticate` means the login the sessions carry is
  gone: renew the token, or add the API key, as "The desk's own login" describes, then run again.
- `phase_output_missing`: a phase ended without writing its file (for example the editor session
  wrote no `edition.json`). Run again.
- `verdicts_invalid`: the checker's verdicts do not cover the check input sentence for sentence, or
  name a different edition. The details list the missing and unknown addresses. Run again; the check
  phase reruns the checker.
- `send_back_overreach`: a story that was not sent back changed between the check rounds. The runner
  rewrites only the stories sent back, so this should not occur; the details name the stories.
  Nothing was published; run again.
- `stray_edits`: a session wrote outside the run directory. The working tree is compared before and
  after each session, so only what the session changed counts; your own uncommitted work elsewhere in
  the repository does not block the paper. The details name the paths. Read the diff, revert what
  should not be there, and run again; nothing was published.
- `input_modified`: a session changed the runner's inputs, or they changed between runs. The inputs
  and the model outputs made beside them are moved to `quarantine-<time>/` inside the run directory,
  kept for inspection, and the next run rebuilds them from block 1 and the publish root. Nothing was
  published; run again.
- `internal_error`: the runner itself raised. The details carry the traceback. Fix, then run again.
- `lock_busy` from block 1 or block 3: another process holds a lock. Wait, then run again. The same
  type from block 2 means another `run` is in progress; `editorial/var/run.lock` names it.
- `not_activated`: `publish` returned but no activation exists. Run block 3's `recover`, then
  `receipt`; never generate a different edition to escape it.
- A failure after the publish (`receipt`, `threads`, `deliver`, `archive`) is resumed by a rerun:
  the run first asks block 3 for the edition's receipt, and when the edition is already
  activated it skips straight to the steps after the publish, each of which is safe to repeat. The
  notification for such a failure says the edition is activated locally but may not be on the site.
  Earlier failures stay in `status.json` under `previous_failures`.
- `recovery_required`: block 3 holds a pending publication from an interrupted run. Run
  `publisher/publish_news.sh recover --publish-root <root>`, then rerun.

A published edition id is never rerun; the next edition corrects it.

## Rehearsing without publishing

`edit_news.sh run --dry-run` does everything up to `publish --dry-run`, which assembles and removes a
release under the publish root, and skips `reconcile`, `receipt`, `threads`, `deliver`,
and `archive`. The `inputs` check and the collect still run. Use it after changing the handbook, the
policy, or a skill.
