# Copenhagen Daily publisher

Block 3 validates an editorial edition and publishes the web newspaper and TRMNL-sized device page.
The public interface is the self-locating `publish_news.sh` JSON command wrapper.

Actions: `list-actions`, `version`, `doctor`, `schema`, `validate`, `check`, `build-web`, `preview`, `fit`,
`render-device`, `publish`, `recover`, `receipt`, and `verify`. The schemas in `contracts/` are the
hand-written boundary shared with the editorial block; generated TypeScript types follow the edition
schema.

The device edition (`src/device/`) is deliberately small: one composition, `lead-wide`, rendered from a
plain TypeScript template into a 1872 × 1404 page whose secondary and brief bands size to their content
and whose lead takes what remains. The device lead is kicker, headline, deck, and source line; its body
is read on the web. A bounded loop measures the page in the pinned Chromium and, when the
lead clips, drops the tallest stories' callouts, demotes secondaries with a brief fallback, omits
optional stories least prominent first, takes the lead's short headline,
and finally trims the tallest remaining story, until every slot fits or a required story cannot be
placed. That ladder can strip more than the page needed, so a restoration pass then puts things back
one at a time and keeps each only if the page still fits: demoted secondaries get their role back,
then omitted optional stories, then reserves, then dropped callouts. The fitting page is captured once,
converted by ImageMagick to a 4-bit greyscale PNG with no dithering, and verified from its bytes.

The web edition is built by Astro from `site/`. In the grid composition the stories below the lead and
its rail are dealt into three fixed stacks at build time (`assets/html/columns.ts`) rather than
balanced by CSS columns, so nothing a reader does moves a story to another column. The site is
unlisted: every page carries a `noindex` robots meta tag (`site/src/layouts/Broadsheet.astro`) and
`site/public/robots.txt` disallows everything. `preview` builds any edition into a scratch site and
serves it on the loopback interface, with the archive index taken from the real publish root when
`--publish-root` is given; it takes `--edition`, `--publish-root`, `--output`, `--layout`, and
`--port` (default 4747).

See [OPERATIONS.md](OPERATIONS.md) for pinned provisioning and verification commands.
