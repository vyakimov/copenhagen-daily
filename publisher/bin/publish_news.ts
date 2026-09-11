#!/usr/bin/env node
import { access, cp, mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { parseArgs, requiredOption } from "../src/cli/args.ts";
import { ACTIONS, actionCatalog } from "../src/cli/actions/list-actions.ts";
import { emit, emitError, type PublisherError } from "../src/contract/envelope.ts";
import { readEdition, validateEdition, type EditionContractV1 } from "../src/contract/edition-contract.ts";
import { CLI_VERSION, ENVELOPE_VERSION, SUPPORTED_EDITION_SCHEMA_VERSIONS } from "../src/contract/version.ts";
import { publishEdition, recoverPublication, activatedReceipt, verifyBundle } from "../src/publish/store.ts";
import { buildWeb, copyAssets, indexEntry, LAYOUT_VERSION } from "../src/publish/web.ts";
import { hashFile } from "../src/publish/hash.ts";
import { publisherError } from "../src/publish/errors.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REQUIRED_NODE_MAJOR = 26;
const args = parseArgs(process.argv.slice(2));
const known = new Set<string>(ACTIONS.map(([name]) => name));
const schemaFiles: Record<string, string> = {
  edition: "edition-contract.v1.schema.json",
  receipt: "publication-receipt.v1.schema.json",
  fit_report: "fit-report.v1.schema.json",
  composition: "composition.v1.schema.json",
  manifest: "manifest.v1.schema.json",
  device_artifact_result: "device-artifact-result.v1.schema.json",
};

const sha256 = (data: string | Buffer) => `sha256:${createHash("sha256").update(data).digest("hex")}`;

function fail(type: string, message: string, details: Record<string, unknown> = {}): never {
  throw publisherError(type, message, details);
}

async function loadValidEdition(path: string): Promise<EditionContractV1> {
  const checked = validateEdition(await readEdition(path));
  if (!checked.valid) {
    const first = checked.issues[0]!;
    fail(first.code, "edition contract is invalid", { issues: checked.issues, pointer: first.pointer });
  }
  return checked.value;
}

function integerOption(name: string, fallback: number, minimum: number): number {
  const raw = args.options.get(name);
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < minimum) {
    fail("usage_error", `--${name} must be an integer of at least ${minimum}`, { option: name, value: raw });
  }
  return value;
}

async function doctor(): Promise<void> {
  const pkg = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  const magick = spawnSync("magick", ["-version"], { encoding: "utf8" });
  const { chromium } = await import("playwright");
  const executable = chromium.executablePath();
  const browserInstalled = await access(executable)
    .then(() => true)
    .catch(() => false);
  const browserVersion = browserInstalled ? spawnSync(executable, ["--version"], { encoding: "utf8" }) : null;
  emit("doctor", {
    node: process.version,
    npm: pkg.packageManager,
    platform: `${process.platform}-${process.arch}`,
    dependencies: {
      astro: pkg.dependencies.astro,
      playwright: pkg.dependencies.playwright,
      ajv: pkg.dependencies.ajv,
      zod: pkg.dependencies.zod,
    },
    imagemagick: magick.status === 0 ? magick.stdout.split("\n")[0] : null,
    browser_installed: browserInstalled,
    chromium_version: browserVersion?.status === 0 ? browserVersion.stdout.trim() : null,
    chromium_executable_sha256: browserInstalled ? await hashFile(executable) : null,
  });
}

async function check(): Promise<void> {
  const checks: Array<[string, string, string[]]> = [
    ["lint", process.execPath, [resolve(root, "scripts/lint.ts")]],
    ["typecheck", resolve(root, "node_modules/.bin/tsc"), ["--noEmit", "--project", resolve(root, "tsconfig.json")]],
    ["tests", process.execPath, ["--test", resolve(root, "tests/**/*.test.ts")]],
    ["wrapper", "/bin/sh", ["-n", resolve(root, "publish_news.sh")]],
  ];
  const results = checks.map(([name, command, commandArgs]) => {
    const r = spawnSync(command, commandArgs, {
      cwd: root,
      encoding: "utf8",
      env: { ...process.env, NO_COLOR: "1" },
    });
    return { name, ok: r.status === 0, exit_code: r.status, output_tail: `${r.stdout}${r.stderr}`.slice(-4000) };
  });
  if (results.some((r) => !r.ok)) fail("check_failed", "offline checks failed", { checks: results });
  emit("check", { checks: results.map(({ name, ok }) => ({ name, ok })) });
}

async function buildWebAction(): Promise<void> {
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const dry = args.options.has("dry-run");
  const work = await mkdtemp(resolve(tmpdir(), "publisher-web-"));
  try {
    const dist = await buildWeb(root, work, edition, [indexEntry(edition, "skipped")]);
    const assets = resolve(work, "assets");
    await copyAssets(root, assets);
    if (!dry) {
      const output = requiredOption(args, "output");
      await mkdir(output, { recursive: true });
      await cp(dist, output, { recursive: true });
      await cp(assets, resolve(output, "a", LAYOUT_VERSION), { recursive: true });
    }
    emit("build-web", {
      status: dry ? "planned" : "built",
      edition_id: edition.edition.id,
      device_status: "skipped",
    });
  } finally {
    await rm(work, { recursive: true, force: true });
  }
}

async function publish(): Promise<void> {
  const skipDevice = args.options.has("skip-device");
  const requireDevice = args.options.has("require-device");
  if (skipDevice && requireDevice) {
    fail("usage_error", "--skip-device and --require-device conflict", {
      options: ["skip-device", "require-device"],
    });
  }
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const result = await publishEdition({
    root: resolve(requiredOption(args, "publish-root")),
    projectRoot: root,
    edition,
    dryRun: args.options.has("dry-run"),
    skipDevice,
    requireDevice,
    keepReleases: integerOption("keep-releases", 5, 1),
    crashAt:
      typeof args.options.get("crash-at") === "string" ? (String(args.options.get("crash-at")) as never) : undefined,
  });
  emit("publish", result);
}

async function main(): Promise<void> {
  const nodeMajor = Number(process.versions.node.split(".")[0]);
  if (nodeMajor !== REQUIRED_NODE_MAJOR) {
    fail("dependency_missing", `Node ${REQUIRED_NODE_MAJOR} is required; running ${process.version}`, {
      required_major: REQUIRED_NODE_MAJOR,
      running: process.version,
    });
  }
  if (!args.action || !known.has(args.action)) {
    fail("usage_error", "unknown or missing action", { actions: [...known].sort() });
  }
  switch (args.action) {
    case "list-actions":
      emit(args.action, { actions: actionCatalog() });
      return;
    case "version":
      emit(args.action, {
        cli_version: CLI_VERSION,
        envelope_version: ENVELOPE_VERSION,
        edition_schema_versions: SUPPORTED_EDITION_SCHEMA_VERSIONS,
      });
      return;
    case "doctor":
      return doctor();
    case "schema": {
      const name = String(args.options.get("name") ?? "edition");
      const file = schemaFiles[name];
      if (!file) fail("usage_error", "unknown schema name", { name, names: Object.keys(schemaFiles).sort() });
      const raw = await readFile(resolve(root, "contracts", file), "utf8");
      emit(args.action, { name, version: 1, sha256: sha256(raw), schema: JSON.parse(raw) });
      return;
    }
    case "validate": {
      const edition = await loadValidEdition(requiredOption(args, "edition"));
      emit(args.action, { edition_id: edition.edition.id, schema_version: edition.schema_version, valid: true });
      return;
    }
    case "build-web":
      return buildWebAction();
    case "publish":
      return publish();
    case "recover":
      emit(
        args.action,
        await recoverPublication(resolve(requiredOption(args, "publish-root")), args.options.has("dry-run")),
      );
      return;
    case "receipt":
      emit(
        args.action,
        await activatedReceipt(resolve(requiredOption(args, "publish-root")), requiredOption(args, "edition")),
      );
      return;
    case "verify":
      emit(
        args.action,
        await verifyBundle(resolve(requiredOption(args, "publish-root")), requiredOption(args, "edition")),
      );
      return;
    case "check":
      return check();
    default:
      fail("usage_error", "action is declared but not available until its implementation batch", {
        action: args.action,
      });
  }
}

try {
  await main();
} catch (caught) {
  const e = caught as Error & { type?: string; details?: Record<string, unknown> };
  const type = e.type ?? "usage_error";
  emitError(args.action || "unknown", {
    type,
    message: e.message,
    details: e.details ?? {},
  } satisfies PublisherError);
  process.exitCode = type === "usage_error" ? 2 : 1;
}
