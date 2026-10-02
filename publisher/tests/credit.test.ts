import test from "node:test";
import assert from "node:assert/strict";
import { quoteNames, sourceCredit, sourceName, storyCredits } from "../assets/html/credit.ts";

const names = {
  publishers: { kristeligt_dagblad: "Kristeligt Dagblad", dr: "DR", berlingske: "Berlingske" },
  agencies: { ritzau: "Ritzau" },
};
const wire = { source: "kristeligt_dagblad", wire: "ritzau", primary: true };
const own = { source: "kristeligt_dagblad", primary: false };
const dr = { source: "dr", primary: false };

test("a wire article is named for its agency, any other for its publisher", () => {
  assert.equal(sourceName(wire, names), "Ritzau");
  assert.equal(sourceName(own, names), "Kristeligt Dagblad");
  assert.equal(sourceName({ source: "unmapped", wire: "unmapped_agency" }, names), "unmapped_agency");
  assert.equal(sourceName({ source: "dr" }, { publishers: names.publishers }), "DR");
});

test("the full credit of a wire article names the agency and its carrier", () => {
  assert.equal(sourceCredit(wire, names), "Ritzau via Kristeligt Dagblad");
  assert.equal(sourceCredit(dr, names), "DR");
});

test("a story's credits name each party once, the primary's first", () => {
  assert.deepEqual(storyCredits([dr, wire, { ...wire, primary: false }], names), ["Ritzau", "DR"]);
  assert.deepEqual(storyCredits([{ ...dr, primary: true }, wire], names), ["DR", "Ritzau"]);
});

test("a carrier that also reports the story itself is credited beside the agency", () => {
  assert.deepEqual(storyCredits([wire, own, dr], names), ["Ritzau", "Kristeligt Dagblad", "DR"]);
});

test("a quote's reporter is the agency only when the publisher's every article in the story is its copy", () => {
  assert.deepEqual(quoteNames([wire, dr], names), { ...names.publishers, kristeligt_dagblad: "Ritzau" });
  assert.deepEqual(quoteNames([wire, own, dr], names), names.publishers);
});
