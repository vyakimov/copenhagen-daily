import test from "node:test";
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");

async function scan(dir: string, forbidden: RegExp): Promise<void> {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error: any) {
    if (error.code === "ENOENT") return;
    throw error;
  }
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await scan(path, forbidden);
    else if (/\.(ts|astro)$/.test(entry.name)) assert.doesNotMatch(await readFile(path, "utf8"), forbidden, path);
  }
}

test("device and site imports remain separate", async () => {
  await scan(join(root, "src/device"), /site\//);
  await scan(join(root, "site"), /src\/device/);
});
