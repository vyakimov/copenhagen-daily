import test from "node:test";
import assert from "node:assert/strict";
import { estimateHeight, splitColumns } from "../assets/html/columns.ts";

const story = (id: string, words: number, callouts = 0) => ({
  id,
  role: "brief",
  copy: {
    headline: `${id} headline`,
    deck: null,
    lede: null,
    body: { standard: [{ text: "word ".repeat(words), sources: [] }] },
  },
  callouts: Array.from({ length: callouts }, () => ({ kind: "figure" })),
  sources: [{ source: "dr" }],
});

test("stories keep contract order and every column is a contiguous run", () => {
  const items = [1, 2, 3, 4, 5, 6, 7].map((n) => ({ key: `s${n}`, lines: 10 }));
  const columns = splitColumns(items, 3);
  assert.equal(columns.length, 3);
  assert.deepEqual(
    columns.flat().map((i) => i.key),
    items.map((i) => i.key),
  );
  assert.ok(columns.every((c) => c.length > 0));
});

test("a tall story does not drag its neighbours into one column", () => {
  const items = [
    { key: "tall", lines: 60 },
    { key: "a", lines: 10 },
    { key: "b", lines: 10 },
    { key: "c", lines: 10 },
    { key: "d", lines: 10 },
    { key: "e", lines: 10 },
  ];
  const columns = splitColumns(items, 3);
  assert.deepEqual(
    columns[0]!.map((i) => i.key),
    ["tall"],
  );
  const heights = columns.map((c) => c.reduce((sum, i) => sum + i.lines, 0));
  assert.ok(
    Math.max(...heights.slice(1)) - Math.min(...heights.slice(1)) <= 10,
    JSON.stringify(heights),
  );
});

test("fewer items than columns leaves the trailing columns empty rather than failing", () => {
  const columns = splitColumns([{ key: "only", lines: 5 }], 3);
  assert.deepEqual(
    columns.map((c) => c.length),
    [1, 0, 0],
  );
});

test("a heading never ends a column: it moves down with the story it introduces", () => {
  const items = [
    { key: "a", lines: 20 },
    { key: "head", lines: 2, leads: true },
    { key: "b", lines: 20 },
    { key: "c", lines: 20 },
  ];
  const columns = splitColumns(items, 3);
  for (const column of columns) {
    const last = column.at(-1);
    assert.ok(!last || !last.leads, "a heading closed a column");
  }
});

test("estimated lines grow with body length, callouts, and long headlines", () => {
  const short = estimateHeight(story("s", 30));
  const long = estimateHeight(story("l", 300));
  const boxed = estimateHeight(story("b", 30, 1));
  assert.ok(long > short && boxed > short);
});

test("a heading and its first story are dealt as one unit, even when they are the only briefs", () => {
  const items = [
    { key: "big", lines: 700 },
    { key: "head", lines: 40, leads: true },
    { key: "brief", lines: 220 },
  ];
  const columns = splitColumns(items, 3);
  const keys = columns.map((c) => c.map((i) => i.key));
  assert.deepEqual(keys, [["big"], ["head", "brief"], []]);
});
