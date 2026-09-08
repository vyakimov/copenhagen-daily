# Source contracts

All feeds are configurable first-party HTTPS RSS endpoints. The FT international homepage feed is an ordered international homepage snapshot (observed at ten items with a 15-minute TTL), not a complete regional homepage. Its UUID GUID is identity; changing `syn-*` URL tracking is removed only from canonical URLs. Page extraction, credentials, and cookies are disabled.

Berlingske was verified on 2026-09-08 using its first-party all-news, Samfund,
Business, Kultur, and Opinion RSS feeds. The stable identity is the complete
`urn:bm:article:<uuid>` GUID. The all-news feed is a latest-news surface; the
category feeds are section surfaces. Preserve `referrer=RSS` in `raw_url` and
remove it from `canonical_url`. The legacy `/content/.../rss` URLs redirect to
publisher-owned `/next-api/feeds/...` endpoints and remain configured because
they are the public, stable feed aliases.
