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
  const v = run(["validate", "--edition", resolve(root, "contracts/examples/minimal.json")]);
  assert.equal(v.status, 0);
  assert.equal(v.body.result.valid, true);
});
