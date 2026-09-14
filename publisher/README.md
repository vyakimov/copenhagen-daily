# Copenhagen Daily publisher

Block 3 validates an editorial edition and publishes the web newspaper and TRMNL-sized device page.
The public interface is the self-locating `publish_news.sh` JSON command wrapper.

The first implementation batch currently provides `list-actions`, `version`, `doctor`, `schema`,
`validate`, and `check`. The schemas in `contracts/` are the hand-written boundary shared with the
editorial block; generated TypeScript types follow the edition schema.

See [OPERATIONS.md](OPERATIONS.md) for pinned provisioning and verification commands. The implementation
plan requires owner review of WP 1–2 before the web/store batch begins.
