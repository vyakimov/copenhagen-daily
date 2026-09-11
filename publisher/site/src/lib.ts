import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const input = process.env.PUBLISHER_BUILD_INPUT;
if (!input || !statSync(input).isDirectory()) throw new Error("PUBLISHER_BUILD_INPUT must name a directory");

export type IndexEntry = {
  id: string;
  date: string;
  name: string;
  language: string;
  cutoff_at: string;
  generated_at: string;
  device_status: "published" | "failed" | "skipped";
};

export const index: { editions: IndexEntry[] } = JSON.parse(readFileSync(resolve(input, "index.json"), "utf8"));
export const config = JSON.parse(readFileSync(resolve(input, "config.json"), "utf8"));

const key = (e: IndexEntry) => `${e.cutoff_at}\0${e.generated_at}\0${e.id}`;
/** Ascending Section 12 order; the archive shows it reversed. */
export const order: IndexEntry[] = [...index.editions].sort((a, b) =>
  key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0,
);
