import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import {
  readEdition,
  validateEdition,
} from "../src/contract/edition-contract.ts";
import { buildWeb, indexEntry } from "../src/publish/web.ts";
import { formatEar } from "../assets/html/format.ts";

const projectRoot = resolve(import.meta.dirname, "..");

test("the ear reads the weekday and the cutoff hour off the cutoff", () => {
  assert.deepEqual(
    formatEar("2026-09-28T06:00:00.000000Z", "en", "Europe/Copenhagen"),
    {
      label: "Monday edition",
      through: "News through 8am, 28 September",
    },
  );
  assert.deepEqual(
    formatEar("2026-09-19T19:49:28.000000Z", "en", "Europe/Copenhagen"),
    {
      label: "Saturday edition",
      through: "News through 9.49pm, 19 September",
    },
  );
  assert.equal(
    formatEar("2026-09-28T06:00:00.000000Z", "da", "Europe/Copenhagen").label,
    "Mandagsudgave",
  );
});

test("every page refuses indexing and the release carries a robots file", async () => {
  const run = await mkdtemp(join(tmpdir(), "publisher-robots-"));
  try {
    const doc = await readEdition(
      resolve(projectRoot, "contracts/examples/minimal.json"),
    );
    const result = validateEdition(doc);
    assert.equal(result.valid, true);
    const edition = result.valid ? result.value : null;
    const dist = await buildWeb(projectRoot, run, edition!, [
      indexEntry(edition!, "skipped"),
    ]);
    const page = await readFile(
      join(dist, "n", edition!.edition.id, "index.html"),
      "utf8",
    );
    assert.match(
      page,
      /<meta name="robots" content="noindex, nofollow, noarchive, noimageindex">/,
    );
    assert.match(page, /(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day edition/);
    const robots = await readFile(join(dist, "robots.txt"), "utf8");
    assert.equal(robots, "User-agent: *\nDisallow: /\n");
  } finally {
    await rm(run, { recursive: true, force: true });
  }
});
