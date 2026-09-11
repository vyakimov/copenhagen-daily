// Offline lint: no tab characters and no line over MAX_LINE in hand-written source.
import { readFile, readdir } from "node:fs/promises";
import { resolve, join } from "node:path";

const MAX_LINE = 120;
const root = resolve(import.meta.dirname, "..");
const roots = ["bin", "src", "scripts", "tests", "site/src", "assets/html", "site/astro.config.mjs"];
const skip = new Set(["src/contract/edition-contract.generated.ts"]);

async function files(path: string): Promise<string[]> {
  const full = join(root, path);
  const entries = await readdir(full, { withFileTypes: true }).catch(() => null);
  if (!entries) return [path];
  const out: string[] = [];
  for (const entry of entries) {
    const rel = join(path, entry.name);
    if (entry.isDirectory()) out.push(...(await files(rel)));
    else if (/\.(ts|mjs|astro)$/.test(entry.name)) out.push(rel);
  }
  return out;
}

const problems: string[] = [];
for (const dir of roots) {
  for (const file of await files(dir)) {
    if (skip.has(file)) continue;
    const lines = (await readFile(join(root, file), "utf8")).split("\n");
    lines.forEach((line, i) => {
      if (line.includes("\t")) problems.push(`${file}:${i + 1}: tab character`);
      if (line.length > MAX_LINE) problems.push(`${file}:${i + 1}: ${line.length} characters (max ${MAX_LINE})`);
    });
  }
}
if (problems.length) {
  process.stderr.write(`${problems.join("\n")}\n`);
  process.exitCode = 1;
}
