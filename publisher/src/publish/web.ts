import { cp, mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { parse } from "yaml";
import type { EditionContractV1 } from "../contract/edition-contract.generated.ts";
import { canonical } from "./hash.ts";
import { publisherError } from "./errors.ts";

import { LAYOUT_VERSION } from "../contract/version.ts";
export { LAYOUT_VERSION };

export type IndexEntry = {
  id: string;
  date: string;
  name: string;
  /** The paper's own number; absent on entries written before it was recorded. */
  number?: number;
  language: string;
  cutoff_at: string;
  generated_at: string;
  device_status: "published" | "failed" | "skipped";
};

export function indexEntry(
  edition: EditionContractV1,
  deviceStatus: IndexEntry["device_status"],
): IndexEntry {
  const e = edition.edition;
  return {
    id: e.id,
    date: e.date,
    name: e.name,
    number: e.number,
    language: e.language,
    cutoff_at: e.cutoff_at,
    generated_at: e.generated_at,
    device_status: deviceStatus,
  };
}

/** Section 12 ordering: cutoff, then generation time, then bytewise id. */
export function orderKey(entry: IndexEntry): string {
  return `${entry.cutoff_at}\0${entry.generated_at}\0${entry.id}`;
}

export function sortEntries(entries: IndexEntry[]): IndexEntry[] {
  return [...entries].sort((a, b) =>
    orderKey(a) < orderKey(b) ? -1 : orderKey(a) > orderKey(b) ? 1 : 0,
  );
}

/**
 * Build the web output for one candidate edition. Only that edition is in the content collection;
 * the archive, latest pointer, and go/ stubs are built from the index snapshot, which is the only
 * way they can know about editions this build does not render.
 */
export async function buildWeb(
  projectRoot: string,
  run: string,
  edition: EditionContractV1,
  entries: IndexEntry[],
  options: { layout?: "grid" | "sheet" } = {},
): Promise<string> {
  const input = resolve(run, "build-input");
  const out = resolve(run, "dist");
  const cache = resolve(run, "astro-cache");
  const generatedSite = resolve(run, "generated", "site");

  await mkdir(resolve(input, "editions"), { recursive: true });
  await mkdir(resolve(run, "generated", "assets"), { recursive: true });
  const sourceSite = resolve(projectRoot, "site");
  await cp(sourceSite, generatedSite, {
    recursive: true,
    filter: (source) => !source.startsWith(resolve(sourceSite, ".astro")),
  });
  await cp(
    resolve(projectRoot, "assets/html"),
    resolve(run, "generated", "assets", "html"),
    { recursive: true },
  );
  await symlink(
    resolve(projectRoot, "node_modules"),
    resolve(run, "node_modules"),
  );

  await writeFile(
    resolve(input, "editions", `${edition.edition.id}.json`),
    canonical(edition),
  );
  await writeFile(
    resolve(input, "index.json"),
    canonical({ editions: sortEntries(entries) }),
  );
  const title = parse(
    await readFile(resolve(projectRoot, "config/title.yaml"), "utf8"),
  );
  // A layout override exists for previews only; publish never passes one.
  if (options.layout) title.web_layout = options.layout;
  // The page links its stylesheet by layout version, so the version is declared once, here.
  title.layout_version = LAYOUT_VERSION;
  await writeFile(resolve(input, "config.json"), canonical(title));

  const result = spawnSync(
    resolve(projectRoot, "node_modules/.bin/astro"),
    ["build", "--root", generatedSite],
    {
      cwd: run,
      encoding: "utf8",
      env: {
        ...process.env,
        ASTRO_TELEMETRY_DISABLED: "1",
        PUBLISHER_BUILD_INPUT: input,
        PUBLISHER_ASTRO_OUT: out,
        PUBLISHER_ASTRO_CACHE: cache,
        PUBLISHER_HYPHENATION: resolve(projectRoot, "config/hyphenation.json"),
        TZ: "Europe/Copenhagen",
        SOURCE_DATE_EPOCH: "0",
      },
    },
  );
  if (result.status !== 0) {
    throw publisherError("web_build_failed", "Astro web build failed", {
      output_tail: `${result.stdout}${result.stderr}`.slice(-4000),
    });
  }
  return out;
}

/** Concatenate tokens + each output stylesheet and copy the vendored fonts into one asset directory. */
export async function copyAssets(
  projectRoot: string,
  dest: string,
): Promise<void> {
  await mkdir(dest, { recursive: true });
  const css = (name: string) =>
    readFile(resolve(projectRoot, "assets/css", name), "utf8");
  const tokens = await css("tokens.css");
  await writeFile(
    resolve(dest, "web.css"),
    `${tokens}\n${await css("web.css")}`,
  );
  await writeFile(
    resolve(dest, "device.css"),
    `${tokens}\n${await css("device.css")}`,
  );
  await cp(resolve(projectRoot, "assets/fonts"), resolve(dest, "fonts"), {
    recursive: true,
  });
}
