import test from "node:test";
import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { hashFile } from "../src/publish/hash.ts";

const root = resolve(import.meta.dirname, "..");

test("font files match the lock and CSS declares the four variable faces", async () => {
  const lock = JSON.parse(await readFile(resolve(root, "assets/fonts/fonts.lock.json"), "utf8"));
  for (const [name, entry] of Object.entries(lock.files) as Array<[string, { sha256: string; bytes: number }]>) {
    assert.equal(await hashFile(resolve(root, "assets/fonts", name)), entry.sha256);
    assert.equal((await stat(resolve(root, "assets/fonts", name))).size, entry.bytes);
    // The 'latin' subset carries ASCII and Latin-1; 'latin-ext' alone does not, and would fall back silently.
    if (name.endsWith(".woff2")) assert.match((entry as any).upstream, /-latin-(opsz|wght)-/, name);
  }
  const css = await readFile(resolve(root, "assets/css/tokens.css"), "utf8");
  assert.equal((css.match(/@font-face/g) ?? []).length, 4);
  assert.match(css, /font-weight:200 800/);
  assert.match(css, /font-weight:100 900/);
});

test("device palette and structural stylesheet invariants are fixed", async () => {
  const tokens = await readFile(resolve(root, "assets/css/tokens.css"), "utf8");
  const device = await readFile(resolve(root, "assets/css/device.css"), "utf8");
  const css = `${tokens} ${device}`;
  for (const [, hex] of css.matchAll(/#([0-9a-fA-F]{6})/g)) {
    assert.equal(hex![0], hex![1]);
    assert.equal(hex![2], hex![3]);
    assert.equal(hex![4], hex![5]);
  }
  assert.match(css, /min-block-size:0/);
  assert.match(css, /overflow:hidden/);
  assert.match(css, /column-fill:auto/);
  assert.doesNotMatch(css, /:nth-child|:first-child|:last-child|[+~]/);
});
