import { escapeHtml } from "./escape.ts";

type Callout = Record<string, unknown>;
const text = (value: unknown) => escapeHtml(String(value));

/** One escaped HTML string per callout kind. The five kinds are the contract's, in Section 5. */
export function renderCallout(callout: Callout): string {
  switch (String(callout.kind)) {
    case "quote":
      return (
        `<aside class="callout quote"><q>${text(callout.text)}</q>` +
        `<footer>${text(callout.attribution)} · ${text(callout.attribution_source)}</footer></aside>`
      );
    case "figure":
      return (
        `<aside class="callout figure"><div class="value">${text(callout.value)}</div>` +
        `<div>${text(callout.label)}</div></aside>`
      );
    case "facts": {
      const items = (callout.items as string[]).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
      return `<aside class="callout facts"><strong>${text(callout.title)}</strong><ul>${items}</ul></aside>`;
    }
    case "box":
      return `<aside class="callout box"><strong>${text(callout.label)}</strong><p>${text(callout.text)}</p></aside>`;
    default: {
      const rows = (callout.rows as Array<{ date: string; text: string }>)
        .map((row) => `<dt>${escapeHtml(row.date)}</dt><dd>${escapeHtml(row.text)}</dd>`)
        .join("");
      return `<aside class="callout timeline"><strong>${text(callout.title)}</strong><dl>${rows}</dl></aside>`;
    }
  }
}
