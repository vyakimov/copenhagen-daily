import { escapeHtml } from "./escape.ts";

type Callout = Record<string, unknown>;
const text = (value: unknown) => escapeHtml(String(value));

/** One escaped HTML string per callout kind, each with its own treatment in web.css and device.css.
 * `publishers` maps publisher ids to display names for a quote's reporting publisher. */
export function renderCallout(callout: Callout, publishers: Record<string, string> = {}): string {
  switch (String(callout.kind)) {
    case "quote": {
      const reporter = publishers[String(callout.attribution_source)] ?? callout.attribution_source;
      return (
        `<aside class="callout quote"><div class="q">“${text(callout.text)}”</div>` +
        `<div class="w">${text(callout.attribution)}, quoted by ${text(reporter)}</div></aside>`
      );
    }
    case "figure":
      return (
        `<aside class="callout figure"><div class="n">${text(callout.value)}</div>` +
        `<div class="l">${text(callout.label)}</div></aside>`
      );
    case "facts": {
      const items = (callout.items as string[]).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
      return `<aside class="callout facts"><div class="t">${text(callout.title)}</div><ul>${items}</ul></aside>`;
    }
    case "box":
      return (
        `<aside class="callout box"><div class="l">${text(callout.label)}</div>` +
        `<div class="t">${text(callout.text)}</div></aside>`
      );
    default: {
      const rows = (callout.rows as Array<{ date: string; text: string }>)
        .map((row) => `<dt>${escapeHtml(row.date)}</dt><dd>${escapeHtml(row.text)}</dd>`)
        .join("");
      return `<aside class="callout timeline"><div class="t">${text(callout.title)}</div><dl>${rows}</dl></aside>`;
    }
  }
}
