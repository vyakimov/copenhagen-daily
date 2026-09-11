import { escapeAttribute, escapeHtml } from "./escape.ts";

type Source = { source: string; url: string };

/** The compact publisher row under a story: one link per contributing article, display names from config. */
export function renderSourceRow(sources: Source[], names: Record<string, string>): string {
  const links = sources
    .map((s) => `<a href="${escapeAttribute(s.url)}">${escapeHtml(names[s.source] ?? s.source)}</a>`)
    .join(" · ");
  return `<div class="source-row">${links}</div>`;
}
