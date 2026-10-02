import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import AjvModule, { type ErrorObject } from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";
import schemaV1 from "../../contracts/edition-contract.v1.schema.json" with { type: "json" };
import schemaV2 from "../../contracts/edition-contract.v2.schema.json" with { type: "json" };
import type { EditionContractV2 } from "./edition-contract.generated.ts";
import { loadTitleConfig, type TitleConfig } from "./title-config.ts";
import { SUPPORTED_EDITION_SCHEMA_VERSIONS } from "./version.ts";

type Version = (typeof SUPPORTED_EDITION_SCHEMA_VERSIONS)[number];
/** An edition of any supported version. Version 2 adds only an optional field to version 1, so its
 * generated type describes both; each document is still validated against its own version's schema. */
export type EditionContract = Omit<EditionContractV2, "schema_version"> & { schema_version: Version };
export type ValidationIssue = { code: string; pointer: string; message: string };
type AjvConstructor = new (options?: Record<string, unknown>) => {
  compile<T>(schema: object): ((data: unknown) => data is T) & { errors?: ErrorObject[] | null };
};
type FormatsFn = (ajv: object, options?: object) => void;
const Ajv2020 = ((AjvModule as unknown as { default?: unknown }).default ?? AjvModule) as unknown as AjvConstructor;
const addFormats = ((addFormatsModule as unknown as { default?: unknown }).default ??
  addFormatsModule) as unknown as FormatsFn;
const ajv = new Ajv2020({
  allErrors: true,
  strict: true,
  coerceTypes: false,
  removeAdditional: false,
  useDefaults: false,
});
addFormats(ajv, { mode: "full" });
const validators = { 1: ajv.compile<EditionContract>(schemaV1), 2: ajv.compile<EditionContract>(schemaV2) };

const escapePointer = (segment: unknown) => String(segment).replaceAll("~", "~0").replaceAll("/", "~1");

function pointerFor(error: ErrorObject): string {
  if (error.keyword === "required") return `${error.instancePath}/${escapePointer(error.params.missingProperty)}`;
  if (error.keyword === "additionalProperties") {
    return `${error.instancePath}/${escapePointer(error.params.additionalProperty)}`;
  }
  return error.instancePath || "/";
}

function issue(pointer: string, message: string): ValidationIssue {
  return { code: "contract_invalid", pointer, message };
}

function semantic(doc: EditionContract, title: TitleConfig): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const publisherNames = title.publishers;
  if (doc.title !== title.id) issues.push(issue("/title", `title must equal the configured title id ${title.id}`));
  const ids = new Set<string>();
  const inputIds = new Set<string>();
  doc.inputs.forEach((input, i) => {
    if (inputIds.has(input.id)) issues.push(issue(`/inputs/${i}/id`, "input id must be unique"));
    inputIds.add(input.id);
  });
  const leads = doc.stories.map((s, i) => [s, i] as const).filter(([s]) => s.role === "lead");
  if (leads.length !== 1) issues.push(issue("/stories", "exactly one lead is required"));
  doc.stories.forEach((story, i) => {
    const p = `/stories/${i}`;
    if (ids.has(story.id)) issues.push(issue(`${p}/id`, "story id must be unique"));
    ids.add(story.id);
    if (
      story.role === "lead" &&
      (i !== 0 || story.device_participation !== "required" || story.fallback_role !== undefined)
    )
      issues.push(issue(`${p}/role`, "the lead must be first, required, and have no fallback"));
    if (story.fallback_role !== undefined && story.role !== "secondary")
      issues.push(issue(`${p}/fallback_role`, "only a secondary may fall back to brief"));
    if ((story.role === "brief" || story.fallback_role === "brief") && !story.copy.lede)
      issues.push(issue(`${p}/copy/lede`, "a story that can be a brief requires a lede"));
    const primary = story.sources.filter((s) => s.primary);
    if (story.sources.length > 0 && primary.length !== 1)
      issues.push(issue(`${p}/sources`, "sources require exactly one primary"));
    story.sources.forEach((source, j) => {
      if (!publisherNames[source.source])
        issues.push(issue(`${p}/sources/${j}/source`, "publisher mapping is unknown"));
      if (source.wire !== undefined && !title.agencies?.[source.wire])
        issues.push(issue(`${p}/sources/${j}/wire`, "agency mapping is unknown"));
      if (!inputIds.has(source.input_id))
        issues.push(issue(`${p}/sources/${j}/input_id`, "input reference does not exist"));
      try {
        const url = new URL(source.url);
        if (url.protocol !== "https:" || url.username || url.password) throw new Error();
      } catch {
        issues.push(issue(`${p}/sources/${j}/url`, "URL must be absolute HTTPS without userinfo"));
      }
    });
    // Citations name publishers, and every cited publisher must have contributed a source to the story.
    const cited = new Set(story.sources.map((s) => s.source));
    const checkCitations = (pointer: string, value: { text: string; sources: string[] } | undefined) => {
      if (!value) return;
      if (story.sources.length > 0 && value.sources.length === 0) {
        issues.push(issue(`${pointer}/sources`, "a sourced story must cite at least one publisher per paragraph"));
      }
      value.sources.forEach((id, k) => {
        if (!cited.has(id))
          issues.push(issue(`${pointer}/sources/${k}`, "cited publisher is not among the story's sources"));
      });
    };
    checkCitations(`${p}/copy/lede`, story.copy.lede);
    for (const [variant, paragraphs] of Object.entries(story.copy.body)) {
      (paragraphs as Array<{ text: string; sources: string[] }>).forEach((paragraph, k) =>
        checkCitations(`${p}/copy/body/${variant}/${k}`, paragraph),
      );
    }
    story.callouts.forEach((callout, k) => {
      if (callout.kind === "quote" && !cited.has(callout.attribution_source)) {
        issues.push(
          issue(
            `${p}/callouts/${k}/attribution_source`,
            "quote attribution names a publisher not among the story's sources",
          ),
        );
      }
    });
  });
  const reserve = doc.stories.filter((s) => s.device_participation === "reserve").map((s) => s.id);
  const optional = doc.stories.filter((s) => s.device_participation === "optional").map((s) => s.id);
  if (JSON.stringify([...doc.fit_policy.reserve_story_ids].sort()) !== JSON.stringify([...reserve].sort()))
    issues.push(issue("/fit_policy/reserve_story_ids", "list must contain every and only reserve story id"));
  if (JSON.stringify([...doc.fit_policy.omittable_story_ids].sort()) !== JSON.stringify([...optional].sort()))
    issues.push(issue("/fit_policy/omittable_story_ids", "list must contain every and only optional story id"));
  const feeds = doc.coverage.feeds;
  if (feeds.length === 0 && doc.coverage.status !== "unknown")
    issues.push(issue("/coverage/status", "an empty inventory requires unknown coverage"));
  if (feeds.some((f) => f.outcome !== "checked") && doc.coverage.status !== "partial")
    issues.push(issue("/coverage/status", "failed or unchecked feeds require partial coverage"));
  if (feeds.length > 0 && feeds.every((f) => f.outcome === "checked") && doc.coverage.status !== "complete")
    issues.push(issue("/coverage/status", "all checked feeds require complete coverage"));
  feeds.forEach((feed, i) => {
    if (feed.outcome === "not_checked" && feed.last_checked_at !== null)
      issues.push(issue(`/coverage/feeds/${i}/last_checked_at`, "not_checked requires null"));
    if (feed.outcome !== "not_checked" && feed.last_checked_at === null)
      issues.push(issue(`/coverage/feeds/${i}/last_checked_at`, "a checked or failed feed requires a timestamp"));
  });
  return issues;
}

export function validateEdition(
  value: unknown,
  title: TitleConfig = loadTitleConfig(),
): { valid: true; value: EditionContract } | { valid: false; issues: ValidationIssue[] } {
  const version = (value as { schema_version?: unknown } | null)?.schema_version;
  if (!value || typeof value !== "object" || !SUPPORTED_EDITION_SCHEMA_VERSIONS.includes(version as Version)) {
    return {
      valid: false,
      issues: [
        {
          code: "contract_unsupported_schema_version",
          pointer: "/schema_version",
          message: `supported edition schema versions are ${SUPPORTED_EDITION_SCHEMA_VERSIONS.join(" and ")}`,
        },
      ],
    };
  }
  const validateSchema = validators[version as Version];
  if (!validateSchema(value))
    return {
      valid: false,
      issues: (validateSchema.errors ?? []).map((e: ErrorObject) => issue(pointerFor(e), e.message ?? "invalid")),
    };
  const edition = value as EditionContract;
  const issues = semantic(edition, title);
  return issues.length ? { valid: false, issues } : { valid: true, value: edition };
}

export async function readEdition(path: string): Promise<unknown> {
  const bytes = await readFile(path);
  if (bytes.byteLength > 4 * 1024 * 1024)
    throw Object.assign(new Error("edition exceeds 4 MiB"), { type: "contract_invalid", details: { pointer: "/" } });
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw Object.assign(new Error("edition must be UTF-8 JSON"), {
      type: "contract_invalid",
      details: { pointer: "/" },
    });
  }
}

export const editionSchemaPath = fileURLToPath(
  new URL("../../contracts/edition-contract.v2.schema.json", import.meta.url),
);
