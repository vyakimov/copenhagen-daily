import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

export const hashBytes = (value: string | Uint8Array): string =>
  `sha256:${createHash("sha256").update(value).digest("hex")}`;

export const hashFile = async (path: string): Promise<string> => hashBytes(await readFile(path));

/** Compact, key-sorted JSON: the byte form every stored document uses. */
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, inner]) => `${JSON.stringify(key)}:${canonical(inner)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}
