import type { APIRoute } from "astro";
import { config, order } from "../lib.ts";
import { escapeHtml } from "../../../assets/html/escape.ts";
import { formatEar, formatEditionDate } from "../../../assets/html/format.ts";

// An Atom feed of editions, one entry each, built from the index snapshot so it lists every edition
// the release holds and not only the one this build renders. Entry ids are permalinks; an edition's
// address never changes once published, which is what Atom asks of an id.
export const GET: APIRoute = () => {
  const site = String(config.site_url ?? "").replace(/\/$/, "");
  const feedUrl = `${site}/feed.xml`;
  const latest = order.at(-1);
  const updated = latest ? latest.generated_at : "1970-01-01T00:00:00Z";
  const entries = [...order].reverse().map((e) => {
    const url = `${site}/n/${e.id}/`;
    const date = formatEditionDate(e.date, e.language);
    const title = `${e.number ? `No. ${e.number}, ` : ""}${date}`;
    const ear = formatEar(e.cutoff_at, e.language, config.device_profile?.timezone ?? "Europe/Copenhagen");
    return `  <entry>
    <id>${escapeHtml(url)}</id>
    <title>${escapeHtml(title)}</title>
    <link rel="alternate" type="text/html" href="${escapeHtml(url)}"/>
    <published>${escapeHtml(e.generated_at)}</published>
    <updated>${escapeHtml(e.generated_at)}</updated>
    <summary>${escapeHtml(`${e.name} of ${config.masthead}. ${ear.through}.`)}</summary>
  </entry>`;
  });
  const xml = `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="${escapeHtml(latest?.language ?? "en")}">
  <id>${escapeHtml(`${site}/`)}</id>
  <title>${escapeHtml(config.masthead)}</title>
  <subtitle>One edition a day, written by machine from publishers' RSS feeds.</subtitle>
  <link rel="self" type="application/atom+xml" href="${escapeHtml(feedUrl)}"/>
  <link rel="alternate" type="text/html" href="${escapeHtml(`${site}/`)}"/>
  <updated>${escapeHtml(updated)}</updated>
  <author><name>${escapeHtml(config.masthead)}</name></author>
${entries.join("\n")}
</feed>
`;
  return new Response(xml, { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
};
