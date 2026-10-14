import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { readEdition, validateEdition } from "../src/contract/edition-contract.ts";
import { buildWeb, indexEntry } from "../src/publish/web.ts";

const projectRoot = resolve(import.meta.dirname, "..");

test("the build emits the about page, the not-found page, and an Atom feed of editions, all linked", async () => {
  const run = await mkdtemp(join(tmpdir(), "publisher-pages-"));
  try {
    const doc = await readEdition(resolve(projectRoot, "contracts/examples/minimal.json"));
    const result = validateEdition(doc);
    assert.equal(result.valid, true);
    const edition = result.valid ? result.value : null;
    const id = edition!.edition.id;
    const dist = await buildWeb(projectRoot, run, edition!, [indexEntry(edition!, "skipped")]);

    const front = await readFile(join(dist, "n", id, "index.html"), "utf8");
    assert.match(front, /<a href="\/about\/">About this paper<\/a>/);
    assert.match(
      front,
      /<link rel="alternate" type="application\/atom\+xml" title="Copenhagen Daily editions" href="\/feed.xml">/,
    );
    const archive = await readFile(join(dist, "archive", "index.html"), "utf8");
    assert.match(archive, /<a href="\/about\/">About this paper<\/a>/);

    const about = await readFile(join(dist, "about", "index.html"), "utf8");
    assert.match(about, /<title>About — Copenhagen Daily<\/title>/);
    assert.match(about, /written by a machine/);
    assert.match(about, /mailto:newsroom@copenhagen-daily.net/);
    assert.match(about, /no analytics, no cookies, no\s+scripts/);
    assert.match(about, /<meta name="robots" content="noindex/);

    const notFound = await readFile(join(dist, "404.html"), "utf8");
    assert.match(notFound, /<title>Not found — Copenhagen Daily<\/title>/);
    assert.match(notFound, /href="\/archive\/"/);
    assert.match(notFound, /href="\/a\/[^"]+\/web.css"/);

    const feed = await readFile(join(dist, "feed.xml"), "utf8");
    assert.match(feed, /^<\?xml version="1.0" encoding="utf-8"\?>\n<feed xmlns="http:\/\/www.w3.org\/2005\/Atom"/);
    assert.match(
      feed,
      /<link rel="self" type="application\/atom\+xml" href="https:\/\/copenhagen-daily.net\/feed.xml"\/>/,
    );
    assert.match(feed, new RegExp(`<id>https://copenhagen-daily.net/n/${id}/</id>`));
    assert.match(feed, new RegExp(`<updated>${edition!.edition.generated_at}</updated>`));
    assert.equal((feed.match(/<entry>/g) ?? []).length, 1);
  } finally {
    await rm(run, { recursive: true, force: true });
  }
});
