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

Publication, recovery, receipt reconciliation, and archive verification use the wrapper:

```sh
./publish_news.sh publish --edition edition.json --publish-root /srv/copenhagen-daily
./publish_news.sh publish --edition edition.json --publish-root /srv/copenhagen-daily --skip-device
./publish_news.sh render-device --edition edition.json --output /tmp/device
./publish_news.sh fit --edition edition.json
./publish_news.sh recover --publish-root /srv/copenhagen-daily
./publish_news.sh receipt --publish-root /srv/copenhagen-daily --edition EDITION_ID
./publish_news.sh verify --publish-root /srv/copenhagen-daily --edition EDITION_ID
```

`publish` renders the device page unless `--skip-device` is given. A device page that cannot be fitted
(`fit_failed_required_story`, `composition_unavailable`, `fit_budget_exhausted`) or rendered
(`renderer_unavailable`, `font_not_loaded`, `render_timeout`, `quantize_failed`) still publishes the web
edition: the result is `status: "partial"` with `device_status: "failed"` and the cause under
`device.error`, exit 0, and `live/device/current.png` keeps the previous edition's bytes. Pass
`--require-device` to activate nothing and exit 1 with the cause instead. Integrity failures
(`network_access_blocked`, `screenshot_size_mismatch`, `image_invariant_violation`,
`measurement_inconsistent`) always stop the run. `render-device` writes `page-1.png`, `page-1.html`,
`composition.json`, and `fit-report.json` into `--output` without touching a publish root, which is the
quickest way to get a PNG for the panel; `fit` only measures and reports. The device page is served
from the docroot at `device/current.png` (the newest edition with a page) and at
`n/<edition-id>/device/page-1.png`.

The device path needs the hermetic Chromium above and `magick` on `PATH`; under cron, where Homebrew's
`/opt/homebrew/bin` is often absent, set `PUBLISHER_MAGICK=/opt/homebrew/bin/magick` in the environment.

`publish --dry-run` completes an isolated build and release assembly in run-owned staging under the
publish root, then removes it; the root is byte-identical afterwards. `recover --dry-run` verifies a
retained intent and every staged or promoted object against the intent's recorded hashes and reports
which promotions and the live swap remain, without advancing them.

Publish and recover, dry runs included, take `<publish-root>/.lock` for the whole run and never wait:
a second run fails at once with `lock_busy` and the lock's age. There is no age-based auto-break. If a
process died, confirm no publisher process is running, remove `.lock`, then run `recover --dry-run`
and `recover`. A crash before the intent is durable leaves nothing behind. A crash after it leaves
`state/pending.json` and the run's `.staging-<release-id>/` directory, which `recover` promotes and
removes; a normal publish refuses to run until then with `recovery_required`.

Activation records under `state/activations/` are numbered by activation sequence and retained
forever, so `receipt` can reconcile a publication whose stdout was lost. After each activation the
publisher deletes releases beyond the newest `--keep-releases` (default 5, minimum 1) by that
sequence, never the live one. Releases are hardlinks, so this frees only the shell; the store and the
records are untouched. A retention failure is a warning on a successful publish.

`verify` checks archived bundle and shared-asset hashes without launching Astro or Chromium. `doctor`
compares current renderer dependencies; a renderer difference calls for visual review but does not
invalidate an archive that passes `verify`. Release-retention cleanup is best effort and cannot turn
an activated publication into a failure.
