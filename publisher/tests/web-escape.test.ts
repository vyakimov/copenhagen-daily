import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { readEdition, validateEdition } from "../src/contract/edition-contract.ts";
import { buildWeb, indexEntry } from "../src/publish/web.ts";

const projectRoot = resolve(import.meta.dirname, "..");
const INJECT = `<script>&"'</div>`;
const ESCAPED = "&lt;script&gt;&amp;&quot;&#39;&lt;/div&gt;";

/**
 * Replace every text field of the fixture with the injection string and return how many of them the
 * web edition renders: it shows the longest body variant only, the lede only on briefs, and never
 * the short headline.
 */
function inject(doc: any): number {
  let rendered = 0;
  const set = (obj: any, key: string, shown = true) => {
    if (typeof obj[key] === "string") {
      obj[key] = INJECT;
      if (shown) rendered += 1;
    }
  };
  set(doc.edition, "name"); // the edition name appears in <title>; the ear is derived from the cutoff
  doc.presentation = { ear_right: INJECT };
  rendered += 1;
  set(doc.coverage, "note");
  for (const story of doc.stories) {
    set(story, "kicker");
    story.kicker_secondary = INJECT;
    rendered += 1;
    set(story.copy, "headline");
    set(story.copy, "headline_short", false);
    set(story.copy, "deck");
    if (story.copy.lede) {
      story.copy.lede.text = INJECT;
      if (story.role === "brief") rendered += 1;
    }
    const longest = story.copy.body.extended ?? story.copy.body.standard ?? story.copy.body.short;
    for (const variant of Object.values(story.copy.body) as Array<Array<{ text: string }>>) {
      for (const paragraph of variant) {
        paragraph.text = INJECT;
        if (variant === longest) rendered += 1;
      }
    }
    for (const callout of story.callouts) {
      for (const key of ["text", "attribution", "value", "label", "title"]) set(callout, key);
      if (callout.items) callout.items = callout.items.map(() => ((rendered += 1), INJECT));
      if (callout.rows) callout.rows = callout.rows.map(() => ((rendered += 2), { date: INJECT, text: INJECT }));
    }
    for (const source of story.sources) set(source, "original_title");
  }
  return rendered;
}

const countTags = (html: string) => ({
  script: (html.match(/<script\b/gi) ?? []).length,
  div: (html.match(/<div\b/gi) ?? []).length,
  a: (html.match(/<a\b/gi) ?? []).length,
  aside: (html.match(/<aside\b/gi) ?? []).length,
  onattr: (html.match(/\son[a-z]+=/gi) ?? []).length,
});

test("the injection string survives the real web build as text and adds no element or attribute", async () => {
  const checked = validateEdition(await readEdition(resolve(projectRoot, "contracts/examples/all-callout-kinds.json")));
  assert.equal(checked.valid, true);
  if (!checked.valid) throw new Error("unreachable");
  const clean = checked.value;
  const injected = structuredClone(clean) as any;
  const injectedFields = inject(injected);
  assert.equal(validateEdition(injected).valid, true, "the injected document must still be a valid contract");

  const work = await mkdtemp(join(tmpdir(), "publisher-escape-"));
  try {
    const pages: string[] = [];
    for (const [name, doc] of [["clean", clean], ["injected", injected]] as const) {
      const dist = await buildWeb(projectRoot, join(work, name), doc, [indexEntry(doc, "skipped")]);
      pages.push(await readFile(join(dist, "n", doc.edition.id, "index.html"), "utf8"));
    }
    // Soft hyphens are presentation inserted at build time; strip them before comparing text.
    const [cleanHtml, injectedHtml] = pages.map((p) => p.replaceAll("\u00ad", "")) as [string, string];
    assert.deepEqual(countTags(injectedHtml), countTags(cleanHtml), "element and handler counts must not change");
    assert.doesNotMatch(injectedHtml, /<script>/);
    const pattern = new RegExp(ESCAPED.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    const recovered = (injectedHtml.match(pattern) ?? []).length;
    assert.equal(recovered, injectedFields, "every rendered field recovers exactly as escaped text");
  } finally {
    await rm(work, { recursive: true, force: true });
  }
});
