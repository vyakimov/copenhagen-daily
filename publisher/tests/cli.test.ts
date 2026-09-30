import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const wrapper = resolve(root, "publish_news.sh");

function run(args: string[], cwd = "/tmp") {
  const r = spawnSync(wrapper, args, { cwd, encoding: "utf8" });
  return { ...r, body: JSON.parse(r.stdout) };
}

test("wrapper is self locating and action catalog is sorted", () => {
  const r = run(["list-actions"]);
  assert.equal(r.status, 0);
  assert.equal(r.stdout.trim().split("\n").length, 1);
  assert.equal(r.body.ok, true);
  const names = r.body.result.actions.map((a: { name: string }) => a.name);
  assert.deepEqual(names, [...names].sort());
});

test("usage errors use exit 2 and one envelope", () => {
  const r = run(["not-an-action"]);
  assert.equal(r.status, 2);
  assert.equal(r.body.error.type, "usage_error");
  assert.equal(r.stdout.trim().split("\n").length, 1);
  const conflict = run([
    "publish",
    "--edition",
    "x.json",
    "--publish-root",
    "/tmp/x",
    "--skip-device",
    "--require-device",
  ]);
  assert.equal(conflict.status, 2);
  assert.equal(conflict.body.error.type, "usage_error");
});

test("schema returns its digest and validate accepts minimal", () => {
  const s = run(["schema", "--name", "edition"]);
  assert.equal(s.status, 0);
  assert.match(s.body.result.sha256, /^sha256:[0-9a-f]{64}$/);
  const v = run([
    "validate",
    "--edition",
    resolve(root, "contracts/examples/minimal.json"),
  ]);
  assert.equal(v.status, 0);
  assert.equal(v.body.result.valid, true);
});

test("unsupported, malformed, and duplicate options are refused before anything is written", async () => {
  const { mkdtemp, readdir } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const fixture = resolve(root, "contracts/examples/minimal.json");
  const unknown = run([
    "validate",
    "--edition",
    fixture,
    "--not-a-real-option",
  ]);
  assert.equal(unknown.status, 2);
  assert.equal(unknown.body.error.type, "usage_error");
  assert.match(unknown.body.error.message, /not-a-real-option/);

  const publishRoot = await mkdtemp(resolve(tmpdir(), "publish-usage-"));
  const misspelt = run([
    "publish",
    "--edition",
    fixture,
    "--publish-root",
    publishRoot,
    "--skip-device",
    "--dryrun",
  ]);
  assert.equal(misspelt.status, 2, misspelt.stdout);
  assert.equal(misspelt.body.error.type, "usage_error");
  assert.deepEqual(
    await readdir(publishRoot),
    [],
    "a refused publish must leave the root untouched",
  );

  const missingValue = run(["validate", "--edition"]);
  assert.equal(missingValue.status, 2);
  const valueOnFlag = run([
    "publish",
    "--edition",
    fixture,
    "--publish-root",
    publishRoot,
    "--skip-device",
    "yes",
  ]);
  assert.equal(valueOnFlag.status, 2, valueOnFlag.stdout);
  assert.equal(valueOnFlag.body.error.type, "usage_error");
  const duplicate = run([
    "validate",
    "--edition",
    fixture,
    "--edition",
    fixture,
  ]);
  assert.equal(duplicate.status, 2);
  const stray = run(["validate", "--edition", fixture, "extra"]);
  assert.equal(stray.status, 2);
  assert.deepEqual(await readdir(publishRoot), []);
});
