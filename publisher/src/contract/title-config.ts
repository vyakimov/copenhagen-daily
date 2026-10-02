import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

export type TitleConfig = {
  id: string;
  masthead: string;
  device_profile: { width: number; height: number; timezone: string };
  composition_order: string[];
  web_layout?: "grid" | "sheet";
  publishers: Record<string, string>;
  agencies?: Record<string, string>;
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
  const shared = Object.keys(config.agencies ?? {}).filter((id) => id in config.publishers);
  if (shared.length > 0) {
    const message = `title config at ${path} names an agency with a publisher's id: ${shared.join(", ")}`;
    throw Object.assign(new Error(message), { type: "publish_root_invalid", details: { path } });
  }
  if (path === titleConfigPath) cached = config;
  return config;
}
