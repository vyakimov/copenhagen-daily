import { escapeAttribute, escapeHtml } from "./escape.ts";

type Source = { source: string; url: string };

/** The compact publisher row under a story: one link per contributing article, display names from config. */
export function renderSourceRow(sources: Source[], names: Record<string, string>): string {
  const links = sources
    .map((s) => `<a href="${escapeAttribute(s.url)}">${escapeHtml(names[s.source] ?? s.source)}</a>`)
    .join(" · ");
  return `<div class="source-row">${links}</div>`;
}

type CitedSource = { source: string; url: string; primary: boolean };

/**
 * The citation marker after a paragraph: one link per cited publisher, to that publisher's article for
 * the story (the primary one when it has several). Emitted without whitespace on purpose: a collapsible
 * newline inside the no-wrap marker makes Chrome's paragraph-level line breaking justify the last line.
 */
export function renderCitations(ids: string[], sources: CitedSource[], names: Record<string, string>): string {
  return ids
    .map((id) => {
      const article = sources.find((s) => s.source === id && s.primary) ?? sources.find((s) => s.source === id);
      const name = escapeHtml(names[id] ?? id);
      return article ? `<a href="${escapeAttribute(article.url)}">${name}</a>` : `<span>${name}</span>`;
    })
    .join("");
}
