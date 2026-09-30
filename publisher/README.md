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
placed. The fitting page is captured once,
converted by ImageMagick to a 4-bit greyscale PNG with no dithering, and verified from its bytes.

See [OPERATIONS.md](OPERATIONS.md) for pinned provisioning and verification commands.
