# Source contracts

All feeds are configurable first-party HTTPS RSS endpoints. The FT international homepage feed is an ordered international homepage snapshot (observed at ten items with a 15-minute TTL), not a complete regional homepage. Its UUID GUID is identity; changing `syn-*` URL tracking is removed only from canonical URLs. Page extraction, credentials, and cookies are disabled.

Berlingske was verified on 2026-09-08 using its first-party all-news, Samfund,
Business, Kultur, and Opinion RSS feeds. The stable identity is the complete
`urn:bm:article:<uuid>` GUID. The all-news feed is a latest-news surface; the
category feeds are section surfaces. Preserve `referrer=RSS` in `raw_url` and
remove it from `canonical_url`. The legacy `/content/.../rss` URLs redirect to
publisher-owned `/next-api/feeds/...` endpoints and remain configured because
they are the public, stable feed aliases.

## Danish expansion (verified 2026-09-14)

Every feed below returned HTTP 200 with parseable RSS and was collected once
end to end with the identity policies in `config/sources.yaml`.

| Source | Identity | Feeds | Notes |
| --- | --- | --- | --- |
| TV 2 (`tv2`) | permalink GUID | `https://feeds.services.tv2.dk/api/feeds/nyheder/rss` (latest, 50 items) | Query parameters such as `?category=` are ignored. The older `feeds.tv2.dk` and `services.tv2.dk` hosts no longer resolve. Sport and weather feeds exist but were stale and are not configured. |
| Jyllands-Posten (`jp`) | `ECE([0-9]+)` from the URL, GUID fallback | `https://feeds.jp.dk/jp/topnyheder` (homepage_rss, 10 items), `https://feeds.jp.dk/jp/seneste` (latest_rss, 10 items) | Public aliases redirect to `newsletter-proxy.aws.jyllands-posten.dk`. A `mest-laeste` feed exists but reflects readership, not editorial placement, so it is not configured. No section feeds. |
| Information (`information`) | GUID `<id> at https://www.information.dk` | `https://www.information.dk/feed` (latest, 20 items) | No section feeds. `pubDate` contains a trailing newline that parsing strips. |
| Altinget (`altinget`) | URL GUID | `https://www.altinget.dk/rss` (latest, 16 items) plus `/<section>/rss` for christiansborg, eu, klima, sundhed, arbejdsmarked, forsvar, kommunal, uddannelse, by | Other sections follow the same pattern; `energi` returns HTML and `digitalisering`, `oekonomi` return 404. |
| Kristeligt Dagblad (`kristeligt_dagblad`) | UUID GUID | `https://www.kristeligt-dagblad.dk/rss/nyheder` (wire-style latest, 10 items), `https://www.kristeligt-dagblad.dk/rss/artikler` (own journalism, 10 items) | `pubDate` is ISO 8601. `rss/kirke`, `rss/kultur`, `rss/debat` redirect to the homepage or return 404. |

Not monitored:

- **Weekendavisen** publishes no RSS feed. Its only machine-readable listing is
  a Google News sitemap at `https://www.weekendavisen.dk/news-sitemap.xml`,
  which the RSS-only collector cannot consume.
- **Zetland** publishes no RSS feed and no article sitemap.

## Via Ritzau (verified 2026-09-15)

`via_ritzau` uses https://via.ritzau.dk/rss/releases/latest, the first-party
Via Ritzau distribution feed for third-party press releases and announcements.
It is not Ritzau's editorial newswire. The endpoint returned HTTP 200 with 25
items. Preserve the complete GUID URL (including `publisherId` and `lang`) as
identity; classify placement as `latest_rss`. The feed contains titles, links,
descriptions, and RFC 2822 publication dates. It does not provide an item-level
sender field, so the source identifies the distribution service, not the author.
Leave the fallback language unset: the observed feed included Greenlandic text
despite `lang=da` in its URLs. Article pages and enclosure images are not fetched.

## International expansion (verified 2026-09-14)

| Source | Identity | Feeds | Notes |
| --- | --- | --- | --- |
| BBC News (`bbc`) | `/(?:articles|videos|live)/([a-z0-9]+)` from the URL, GUID fallback | `feeds.bbci.co.uk/news/rss.xml` (homepage_rss) plus world, europe, business, technology, science_and_environment, health, politics, entertainment_and_arts | GUIDs end in a per-feed `#N` fragment, so the URL id is the identity. Feeds list some articles twice; the repeat is quarantined as `duplicate_in_snapshot`. |
| The Economist (`economist`) | UUID GUID | `/latest/rss.xml` (latest) plus leaders, briefing, europe, international, finance-and-economics, business, science-and-technology, culture | 300 items per feed (~150 KB). `/rss` returns 403. |
| The Guardian (`guardian`) | GUID (URL) | `/international/rss` (homepage_rss) plus world, europe-news, uk/business, uk/technology, uk/environment, science, uk/culture, uk/commentisfree | Large feeds (100+ items, ~380 KB). |
| The Washington Post (`wapo`) | GUID (URL) | `feeds.washingtonpost.com/rss/{world,national,politics,business,business/technology,opinions}` | Small feeds (2–13 items). `rss/homepage` returns 400. |
| The Wall Street Journal (`wsj`) | GUID (`WP-WSJ-…`) | `feeds.content.dowjones.io/public/rss/{RSSWorldNews,WSJcomUSBusiness,RSSMarketsMain,socialeconomyfeed,socialpoliticsfeed,RSSWSJD,RSSOpinion}` | The `feeds.a.dj.com` aliases still answer but stopped updating in January 2025. Feeds list some items twice. |

Not monitored:

- **Reuters** publishes no RSS feed; every `reuters.com` feed path returns 401 to
  any client.
- **The Associated Press** returns 403 from `apnews.com` for every feed path,
  including with a browser user agent.
