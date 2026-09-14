import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Build-time discretionary hyphenation. Soft hyphens (U+00AD) are inserted at pattern breakpoints so
// every browser, and the pinned device Chromium, breaks words at the same places; the stylesheets set
// hyphens:manual so no browser dictionary is consulted. Approved copy is unchanged: a soft hyphen is
// presentation, invisible unless a line breaks there, and edition.json never carries one.

const require = createRequire(import.meta.url);

type Hyphenator = { hyphenateSync(text: string, options?: { hyphenChar?: string; minWordLength?: number }): string };
type Config = { min_word: number; left: number; right: number; exceptions: Record<string, Record<string, string>> };

const SOFT = "\u00ad";
const patterns: Record<string, string> = { en: "hyphen/en-gb", da: "hyphen/da" };
const loaded = new Map<string, Hyphenator>();
// The CLI names the config file through the environment because the site build bundles this module
// into a chunk whose location no longer relates to config/; tests and the CLI fall back to the source path.
const configPath =
  process.env.PUBLISHER_HYPHENATION ?? fileURLToPath(new URL("../../config/hyphenation.json", import.meta.url));
const config: Config = JSON.parse(readFileSync(configPath, "utf8"));

function hyphenator(language: string): Hyphenator | null {
  const module = patterns[language];
  if (!module) return null;
  if (!loaded.has(module)) loaded.set(module, require(module) as Hyphenator);
  return loaded.get(module)!;
}

/** Break points for one word, after the exception list and the left/right limits. */
export function hyphenateWord(word: string, language: string): string {
  const exception = config.exceptions[language]?.[word.toLowerCase()];
  if (exception) {
    // Exceptions are written with ordinary hyphens; keep the word's own casing.
    const parts = exception.split("-");
    let index = 0;
    return parts.map((part) => word.slice(index, (index += part.length))).join(SOFT);
  }
  if (word.length < config.min_word) return word;
  const engine = hyphenator(language);
  if (!engine) return word;
  const pieces = engine.hyphenateSync(word, { hyphenChar: SOFT, minWordLength: config.min_word }).split(SOFT);
  let out = pieces[0]!;
  for (let i = 1; i < pieces.length; i += 1) {
    const before = out.length;
    const after = pieces.slice(i).join("").length;
    out += (before >= config.left && after >= config.right ? SOFT : "") + pieces[i];
  }
  return out;
}

/** Insert soft hyphens into running text. Only runs of letters are touched; anything else is left as is. */
export function softHyphenate(text: string, language: string): string {
  if (!hyphenator(language)) return text;
  return text.replace(/\p{L}+/gu, (word) => hyphenateWord(word, language));
}
