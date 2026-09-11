import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

export type TitleConfig = {
  id: string;
  masthead: string;
  device_profile: { width: number; height: number; timezone: string };
  composition_order: string[];
  publishers: Record<string, string>;
};

export const titleConfigPath = fileURLToPath(new URL("../../config/title.yaml", import.meta.url));

let cached: TitleConfig | undefined;

export function loadTitleConfig(path: string = titleConfigPath): TitleConfig {
  if (path === titleConfigPath && cached) return cached;
  const raw = parse(readFileSync(path, "utf8")) as Partial<TitleConfig> | null;
  if (!raw || typeof raw.id !== "string" || !raw.publishers || typeof raw.publishers !== "object") {
    throw Object.assign(new Error(`title config at ${path} is missing id or publishers`), {
      type: "publish_root_invalid",
      details: { path },
    });
  }
  const config = raw as TitleConfig;
  if (path === titleConfigPath) cached = config;
  return config;
}
