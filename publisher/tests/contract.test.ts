import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import AjvModule from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";
import { validateEdition } from "../src/contract/edition-contract.ts";

const root = resolve(import.meta.dirname, "..");
const examples = resolve(root, "contracts/examples");
const readJson = async (path: string) => JSON.parse(await readFile(path, "utf8"));
const Ajv2020 = ((AjvModule as unknown as { default?: unknown }).default ?? AjvModule) as unknown as new (
  o?: object,
) => { compile(s: object): ((d: unknown) => boolean) & { errors?: unknown } };
const addFormats = ((addFormatsModule as unknown as { default?: unknown }).default ??
  addFormatsModule) as unknown as (a: object, o?: object) => void;

test("all eight golden editions validate", async () => {
  const files = (await readdir(examples)).filter((f) => f.endsWith(".json")).sort();
  assert.deepEqual(files, [
    "all-callout-kinds.json",
    "danish.json",
    "dense.json",
    "long-headline.json",
    "minimal.json",
    "partial-coverage.json",
    "required-overflow.json",
    "sparse.json",
  ]);
  for (const file of files) {
    const result = validateEdition(await readJson(resolve(examples, file)));
    assert.equal(result.valid, true, `${file}: ${JSON.stringify(!result.valid && result.issues)}`);
  }
});

test("every independently versioned artifact example validates against its schema", async () => {
  for (const name of ["composition", "device-artifact-result", "fit-report", "manifest", "publication-receipt"]) {
    const schema = await readJson(resolve(root, `contracts/${name}.v1.schema.json`));
    assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema", name);
    assert.equal(schema.additionalProperties, false, `${name} must reject unknown fields`);
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv, { mode: "full" });
    const validate = ajv.compile(schema);
    const example = await readJson(resolve(examples, `artifacts/${name}.v1.json`));
    assert.equal(validate(example), true, `${name}: ${JSON.stringify(validate.errors)}`);
  }
});

type Op = { op: "add" | "replace" | "remove"; path: string; value?: unknown };
type RejectionCase = { name: string; invariant: string; ops: Op[]; expected_code: string; expected_pointer: string };

function applyOps(document: unknown, ops: Op[]): unknown {
  const doc = structuredClone(document);
  for (const { op, path, value } of ops) {
    const parts = path
      .split("/")
      .slice(1)
      .map((p) => p.replaceAll("~1", "/").replaceAll("~0", "~"));
    const key = parts.pop()!;
    let target: any = doc;
    for (const part of parts) target = target[Array.isArray(target) ? Number(part) : part];
    if (Array.isArray(target)) {
      const index = Number(key);
      if (op === "add") target.splice(index, 0, value);
      else if (op === "replace") target[index] = value;
      else target.splice(index, 1);
    } else if (op === "remove") delete target[key];
    else target[key] = value;
  }
  return doc;
}

test("the rejection corpus rejects each document with the expected code and pointer", async () => {
  const corpus = (await readJson(resolve(examples, "rejections/cases.json"))) as {
    base: string;
    cases: RejectionCase[];
  };
  const base = await readJson(resolve(examples, corpus.base));
  assert.equal(validateEdition(base).valid, true);
  for (const c of corpus.cases) {
    const result = validateEdition(applyOps(base, c.ops));
    assert.equal(result.valid, false, `${c.name} should be rejected (${c.invariant})`);
    if (result.valid) continue;
    assert.equal(result.issues[0]?.code, c.expected_code, `${c.name}: code`);
    assert.equal(
      result.issues[0]?.pointer,
      c.expected_pointer,
      `${c.name}: pointer, got ${JSON.stringify(result.issues)}`,
    );
  }
});
