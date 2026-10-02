// Device page template: one frozen plan -> one complete HTML document string. No links, no scripts.
// The lead-wide composition: masthead, lead, a band of up to three secondaries, a strip of up to four
// briefs, folio. Empty bands are omitted and the lead takes the room; nothing scales with copy length.
import { escapeHtml } from "../../assets/html/escape.ts";
import { renderCallout } from "../../assets/html/callout.ts";
import { quoteNames, sourceName, storyCredits, type CreditNames } from "../../assets/html/credit.ts";
import { formatCutoff, formatEditionDate } from "../../assets/html/format.ts";
import { softHyphenate } from "../../assets/html/hyphenate.ts";
import type { Story } from "../contract/edition-contract.generated.ts";
import type { EditionContract } from "../contract/edition-contract.ts";
import { LAYOUT_VERSION } from "../contract/version.ts";

export type BodyVariant = "extended" | "standard" | "short";
export type Placement = {
  story_id: string;
  role_as_placed: "lead" | "secondary" | "brief";
  slot: string;
  headline_variant: "headline" | "headline_short";
  copy_variant: BodyVariant | null;
  callout_index: number | null;
};
export type DevicePlan = {
  composition: "lead-wide";
  placements: Placement[];
  omitted: Array<{ story_id: string; reason: string }>;
  dropped_callouts: Array<{ story_id: string; index: number; reason: string }>;
};

export const CAPACITY = { secondary: 3, brief: 4 } as const;
/** The same versioned path the release publishes the stylesheet at, so the saved page loads it from the docroot. */
export const STYLESHEET_URL = `/a/${LAYOUT_VERSION}/device.css`;

const e = escapeHtml;

function leadingPublishers(stories: Story[], names: CreditNames): string[] {
  const count = new Map<string, number>();
  for (const s of stories) {
    for (const name of storyCredits(s.sources, names)) count.set(name, (count.get(name) ?? 0) + 1);
  }
  return [...count.keys()].sort((a, b) => count.get(b)! - count.get(a)! || a.localeCompare(b)).slice(0, 5);
}

function sourceRow(story: Story, names: CreditNames): string {
  const credits = storyCredits(story.sources, names);
  if (credits.length === 0) return "";
  // The panel names the primary and up to three more publishers; the web page carries the full list.
  const shown = credits.slice(0, 4).map(e);
  const more = credits.length > 4 ? ` · +${credits.length - 4}` : "";
  return `<div class="src">${shown.join(" · ")}${more}</div>`;
}

function kicker(story: Story, publisher?: string): string {
  const second = publisher ?? story.kicker_secondary;
  const sec = second ? ` <span class="sec">· ${e(second)}</span>` : "";
  return `<div class="kicker">${e(story.kicker)}${sec}</div>`;
}

function primaryName(story: Story, names: CreditNames): string | undefined {
  const primary = story.sources.find((s) => s.primary) ?? story.sources[0];
  return primary ? sourceName(primary, names) : undefined;
}

function paragraphs(story: Story, variant: BodyVariant | null, language: string): string {
  const body = variant ? story.copy.body[variant] : undefined;
  if (!body) return "";
  return body.map((p, i) => `<p${i === 0 ? ' class="p0"' : ""}>${e(softHyphenate(p.text, language))}</p>`).join("");
}

function cellClass(index: number, total: number): string {
  const parts = ["cell"];
  if (index === 0) parts.push("first");
  else parts.push("sep");
  if (index === total - 1) parts.push("last");
  return parts.join(" ");
}

export function renderDevicePage(
  edition: EditionContract,
  plan: DevicePlan,
  config: { masthead: string } & CreditNames,
): string {
  const meta = edition.edition;
  const byId = new Map(edition.stories.map((s) => [s.id, s]));
  const names: CreditNames = { publishers: config.publishers, agencies: config.agencies };
  const language = meta.language;
  const placed = plan.placements.map((p) => ({ p, story: byId.get(p.story_id)! }));
  const lead = placed.find((x) => x.p.role_as_placed === "lead");
  const secondaries = placed.filter((x) => x.p.role_as_placed === "secondary");
  const briefs = placed.filter((x) => x.p.role_as_placed === "brief");
  const callout = (story: Story, index: number | null) =>
    index === null
      ? ""
      : renderCallout(story.callouts[index] as Record<string, unknown>, quoteNames(story.sources, names));
  const headline = (story: Story, variant: Placement["headline_variant"]) =>
    e(variant === "headline_short" && story.copy.headline_short ? story.copy.headline_short : story.copy.headline);

  let leadHtml = "";
  if (lead) {
    const { p, story } = lead;
    // The device lead is kicker, headline, deck, and source line; a callout, when one fits, sits to
    // the right of the text. The lead's body is read on the web.
    const aside = callout(story, p.callout_index);
    const text =
      kicker(story) +
      `<h1>${headline(story, p.headline_variant)}</h1>` +
      (story.copy.deck ? `<p class="deck">${e(story.copy.deck)}</p>` : "") +
      sourceRow(story, names);
    leadHtml =
      `<article class="lead slot" data-slot="${p.slot}"><div class="story">` +
      (aside ? `<div class="lead-flow"><div>${text}</div><div class="aside">${aside}</div></div>` : text) +
      `</div></article>`;
  }

  const secondaryHtml =
    secondaries.length === 0
      ? ""
      : `<section class="band secondaries cols-${secondaries.length}">` +
        secondaries
          .map(
            ({ p, story }, i) =>
              `<article class="slot ${cellClass(i, secondaries.length)}" data-slot="${p.slot}">` +
              `<div class="story">${kicker(story)}` +
              `<h2>${headline(story, p.headline_variant)}</h2>` +
              callout(story, p.callout_index) +
              `<div class="body">${paragraphs(story, p.copy_variant, language)}</div>` +
              sourceRow(story, names) +
              `</div></article>`,
          )
          .join("") +
        `</section>`;

  const briefsHtml =
    briefs.length === 0
      ? ""
      : `<section class="band briefs"><div class="head">In brief</div><div class="strip cols-${briefs.length}">` +
        briefs
          .map(
            ({ p, story }, i) =>
              `<article class="slot ${cellClass(i, briefs.length)}" data-slot="${p.slot}">` +
              `<div class="story">${kicker(story, primaryName(story, names))}` +
              `<h3>${headline(story, p.headline_variant)}</h3>` +
              (story.copy.lede ? `<p class="lede">${e(softHyphenate(story.copy.lede.text, language))}</p>` : "") +
              `</div></article>`,
          )
          .join("") +
        `</div></section>`;

  const cutoff = formatCutoff(meta.cutoff_at, language, meta.timezone);
  const date = formatEditionDate(meta.date, language);
  const leading = leadingPublishers(
    placed.map((x) => x.story),
    names,
  );
  return (
    `<!doctype html><html lang="${e(language)}"><head><meta charset="utf-8">` +
    `<title>${e(config.masthead)} ${e(meta.date)}</title>` +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; font-src 'self'">` +
    `<link rel="stylesheet" href="${STYLESHEET_URL}"></head><body><main class="device-page">` +
    `<header class="masthead"><div class="ear"><span class="lbl">${e(meta.name)}</span></div>` +
    `<div class="title">${e(config.masthead)}</div><div class="ear right"></div></header>` +
    `<div class="dateline"><span>${e(date)}</span><span class="mid">No. ${meta.number}</span>` +
    `<span>${leading.map(e).join(" · ")}</span></div>` +
    leadHtml +
    secondaryHtml +
    briefsHtml +
    `<footer class="folio"><span><b>${e(config.masthead)}</b> · ${e(meta.name)} · No. ${meta.number}</span>` +
    `<span>News through ${e(cutoff)} · Coverage ${e(edition.coverage.status)}</span></footer>` +
    `</main></body></html>`
  );
}
