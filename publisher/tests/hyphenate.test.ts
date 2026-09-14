import test from "node:test";
import assert from "node:assert/strict";
import { hyphenateWord, softHyphenate } from "../assets/html/hyphenate.ts";

const SOFT = "\u00ad";
const show = (s: string) => s.replaceAll(SOFT, "-");

test("English and Danish words get soft hyphens within the configured limits", () => {
  assert.equal(show(hyphenateWord("generation", "en")), "gen-er-a-tion");
  assert.equal(show(hyphenateWord("decision", "en")), "de-cision");
  assert.equal(show(hyphenateWord("borgere", "da")), "bor-gere");
  // Two letters may be left behind, three must be carried over: "be-gins" yes, "begi-ns" never.
  for (const word of ["begins", "construction", "municipalities"]) {
    for (const piece of hyphenateWord(word, "en").split(SOFT).slice(0, -1)) assert.ok(piece.length >= 2, word);
    const last = hyphenateWord(word, "en").split(SOFT).at(-1)!;
    assert.ok(last.length >= 3, word);
  }
});

test("short words, exceptions, and non-letter tokens", () => {
  assert.equal(hyphenateWord("vote", "en"), "vote");
  assert.equal(show(hyphenateWord("Broadcaster", "en")), "Broad-caster");
  assert.equal(show(hyphenateWord("Nationalbanken", "en")), "National-banken");
  const text = "Reserves rose by 14 billion kroner; see https://example.com/generation and <script>.";
  const out = softHyphenate(text, "en");
  assert.equal(out.replaceAll(SOFT, ""), text, "soft hyphens are the only change");
  assert.ok(!out.includes("14" + SOFT) && !out.includes(SOFT + "14"));
  assert.equal(softHyphenate("generation", "fr"), "generation", "unknown language: untouched");
});

test("hyphenation is deterministic", () => {
  const text =
    "Copenhagen's city council voted early on Tuesday to back the eastern harbour tunnel, ending a debate.";
  assert.equal(softHyphenate(text, "en"), softHyphenate(text, "en"));
  assert.ok(softHyphenate(text, "en").includes(SOFT));
});
