# Publisher operations

Provision with Node 26.5.0, npm 11.17.0, and ImageMagick 7.1.2-31:

```sh
cd publisher
npm ci
PLAYWRIGHT_BROWSERS_PATH=0 node_modules/.bin/playwright install --no-shell chromium
```

Routine commands go through `publish_news.sh`. Never run the Astro dev server against `site/`: dev mode
injects a Vite client script and opens a websocket, which invariant 2 forbids, and it writes cache
directories into the source tree. Build through the wrapper only. The wrapper never installs or downloads anything.
Run `./publish_news.sh check` for the offline verification suite and `doctor` for dependency identities.
Every action's options are declared in `src/cli/options.ts` and checked before the action runs: an
unknown, repeated, or positional option, a value option without a value, or a flag given a value is a
`usage_error` with exit 2.

Publication, preview, recovery, receipt reconciliation, and archive verification use the wrapper:

```sh
./publish_news.sh publish --edition edition.json --publish-root /srv/copenhagen-daily
./publish_news.sh publish --edition edition.json --publish-root /srv/copenhagen-daily --skip-device
./publish_news.sh preview --edition edition.json --publish-root /srv/copenhagen-daily
./publish_news.sh render-device --edition edition.json --output /tmp/device
./publish_news.sh fit --edition edition.json
./publish_news.sh recover --publish-root /srv/copenhagen-daily
./publish_news.sh receipt --publish-root /srv/copenhagen-daily --edition EDITION_ID
./publish_news.sh verify --publish-root /srv/copenhagen-daily --edition EDITION_ID
```

`preview` builds one edition into a scratch site and serves it on `127.0.0.1` (`--port`, default
4747) until Ctrl-C, writing nothing to the store. With `--publish-root` the archive and the prev/next
stubs come from that root's live index, so navigation is the real thing; `--layout grid|sheet`
overrides the composition and `--output DIR` writes the site there instead of serving it.

The layout version is `broadsheet-v4` (`src/contract/version.ts`). Every web page links
`/a/<layout version>/web.css` and the device page `/a/<layout version>/device.css`; a release carries
every layout version the store holds, so archived pages keep the stylesheet they were published with.
The archive page is a register grouped by month, numbered by the paper's own number carried in the
index.

`publish` renders the device page unless `--skip-device` is given; scheduled runs render it because
the desk asks for it (`device: true` in `editorial/config/desk.yaml`). A device page that cannot be
fitted (`fit_failed_required_story`, `fit_failed_layout`, `composition_unavailable`,
`fit_budget_exhausted`) or rendered (`dependency_missing` when Playwright is not installed,
`renderer_unavailable`, `font_not_loaded`, `render_timeout`, `quantize_failed`) still publishes the web
edition: the result is `status: "partial"` with `device_status: "failed"` and the cause under
`device.error`, exit 0, and `live/device/current.png` keeps the previous edition's bytes. Pass
`--require-device` to activate nothing and exit 1 with the cause instead. Only the integrity failures
listed in `DEVICE_INTEGRITY_ERRORS` (`src/device/index.ts`: `network_access_blocked`,
`screenshot_size_mismatch`, `image_invariant_violation`, `measurement_inconsistent`) stop the run.
`render-device` writes `page-1.png`, `page-1.html`,
`composition.json`, and `fit-report.json` into `--output` without touching a publish root, which is the
quickest way to get a PNG for the panel; `fit` only measures and reports. The device page is served
from the docroot at `device/current.png` (the newest edition with a page) and at
`n/<edition-id>/device/page-1.png`; the kitchen screen reads
`https://copenhagen-daily.net/device/current.png`. Block 3 itself uploads nothing: syncing `live/` to
the bucket is the desk's phase, see `editorial/OPERATIONS.md`.

The device path needs the hermetic Chromium above and `magick` on `PATH`; under cron, where Homebrew's
`/opt/homebrew/bin` is often absent, set `PUBLISHER_MAGICK=/opt/homebrew/bin/magick` in the environment.

`publish --dry-run` completes an isolated build and release assembly in run-owned staging under the
publish root, then removes it; a published root is byte-identical afterwards, while a root that has
never been published keeps the empty `store/` and `releases/` directories the run created. `recover --dry-run` verifies a
retained intent and every staged or promoted object against the intent's recorded hashes and reports
which promotions and the live swap remain, without advancing them.

Publish and recover, dry runs included, take `<publish-root>/.lock` for the whole run and never wait:
a second run fails at once with `lock_busy` and the lock's age. There is no age-based auto-break. The
lock is a directory made with `mkdir`. If a process died, confirm no publisher process is running,
remove `.lock` (`rmdir` or `rm -r`), then run `recover --dry-run` and `recover`. A run that fails
before the intent is durable removes its own staging; a process killed outright before that point
leaves `.staging-<release-id>/` behind, and `recover` reports `nothing_to_recover` without removing
it, so delete it by hand. A crash after the intent leaves `state/pending.json` and the run's
`.staging-<release-id>/` directory; a normal publish refuses to run until then with
`recovery_required`. `recover` promotes what is still staged, swaps `live` (replacing a leftover
`.live-<release-id>` symlink from the crashed run, and refusing with `publish_conflict` if that path is
not a symlink), writes the activation record or, when a matching record already exists, only clears
`state/pending.json`, removes the staging directory, and retains 5 releases; it takes no
`--keep-releases`.

Activation records under `state/activations/` are named `<release-id>.json`, where the release id is
`release-<edition-id>-<uuid>`, carry the activation sequence as a field, and are retained forever, so
`receipt` can reconcile a publication whose stdout was lost. After each activation the
publisher deletes releases beyond the newest `--keep-releases` (default 5, minimum 1) by that
sequence, never the live one. Releases are hardlinks, so this frees only the shell; the store and the
records are untouched. A retention failure is a warning on a successful publish.

`verify` checks archived bundle and shared-asset hashes without launching Astro or Chromium. For an
activated edition, `verify` and `receipt` also require the manifest digest to equal the one in the
activation record and fail with `bundle_integrity_failed` otherwise. `doctor` reports the identities of
the current renderer dependencies and takes no options; a renderer difference from an archived
manifest's `environment` calls for visual review but does not invalidate an archive that passes
`verify`. Release-retention cleanup is best effort and cannot turn an activated publication into a
failure.
