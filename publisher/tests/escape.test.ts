import test from "node:test";
import assert from "node:assert/strict";
import { escapeHtml } from "../assets/html/escape.ts";
import { renderCallout } from "../assets/html/callout.ts";
import { renderSourceRow } from "../assets/html/source-row.ts";
import { formatCutoff, formatEditionDate, formatPublished } from "../assets/html/format.ts";

test("shared HTML helpers escape the fixed injection string", () => {
  const value = `<script>&"'</div>`;
  const outputs = [
    escapeHtml(value),
    renderCallout({ kind: "box", label: value, text: value }),
    renderCallout({ kind: "quote", text: value, attribution: value, attribution_source: "x" }, { x: value }),
    renderSourceRow([{ source: value, url: "https://example.com/?q=%22" }], { [value]: value }),
  ];
  for (const html of outputs) {
    assert.doesNotMatch(html, /<script>/);
    assert.doesNotMatch(html, /<\/div><\/a>/);
    assert.match(html, /&lt;script&gt;&amp;&quot;&#39;&lt;\/div&gt;/);
  }
});

test("reader-facing dates are formatted in the edition language and timezone", () => {
  // Exact punctuation belongs to the ICU version the manifest records, so assert the shape only.
  assert.match(formatEditionDate("2026-09-09", "en"), /^Wednesday,? 9 September 2026$/);
  assert.match(formatEditionDate("2026-09-09", "da"), /^onsdag den 9\. september 2026$/);
  const cutoff = formatCutoff("2026-09-09T03:00:00.000000Z", "en", "Europe/Copenhagen");
  assert.match(cutoff, /^05:00, Wednesday,? 9 September$/);
  assert.match(formatPublished("2026-09-08T14:00:00.000000Z", "en", "Europe/Copenhagen"), /^8 Sept? 2026, 16:00$/);
});
