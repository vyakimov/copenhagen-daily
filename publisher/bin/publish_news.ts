#!/usr/bin/env node
import { access, cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { extname, join } from "node:path";
import { tmpdir } from "node:os";
import { parseArgs, requiredOption } from "../src/cli/args.ts";
import { ACTIONS, actionCatalog } from "../src/cli/actions/list-actions.ts";
import { emit, emitError, type PublisherError } from "../src/contract/envelope.ts";
import { readEdition, validateEdition, type EditionContractV1 } from "../src/contract/edition-contract.ts";
import { CLI_VERSION, ENVELOPE_VERSION, SUPPORTED_EDITION_SCHEMA_VERSIONS } from "../src/contract/version.ts";
import {
  publishEdition,
  recoverPublication,
  activatedReceipt,
  verifyBundle,
  currentIndex,
} from "../src/publish/store.ts";
import { buildWeb, copyAssets, indexEntry, LAYOUT_VERSION } from "../src/publish/web.ts";
import { canonical, hashBytes, hashFile } from "../src/publish/hash.ts";
import { publisherError } from "../src/publish/errors.ts";
import { loadTitleConfig } from "../src/contract/title-config.ts";
import { buildDevice, withBrowser } from "../src/device/index.ts";
import { fitEdition } from "../src/device/fit.ts";

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

const PREVIEW_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
};

/**
 * Build one edition into a scratch site and serve it on the loopback interface. The archive and the
 * prev/next stubs come from the publish root's index when one is given, so navigation is the real
 * thing; nothing is written to the store. With --output the site is written there instead of served.
 */
function stringOption(name: string): string | undefined {
  const value = args.options.get(name);
  if (value === true) fail("usage_error", `--${name} needs a value`, { option: name });
  return value;
}

async function preview(): Promise<void> {
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const layout = args.options.get("layout");
  if (layout !== undefined && layout !== "grid" && layout !== "sheet") {
    fail("usage_error", "--layout must be grid or sheet", { option: "layout", value: layout });
  }
  const publishRoot = stringOption("publish-root");
  const prior = publishRoot ? await currentIndex(resolve(publishRoot)) : [];
  const entries = [...prior.filter((e) => e.id !== edition.edition.id), indexEntry(edition, "skipped")];
  const work = await mkdtemp(resolve(tmpdir(), "publisher-preview-"));
  const dist = await buildWeb(root, work, edition, entries, { layout: layout as never });
  await copyAssets(root, resolve(dist, "a", LAYOUT_VERSION));
  // "/" is the previewed edition's own page, as it would be in a release, whatever the index says is latest.
  await cp(resolve(dist, "n", edition.edition.id, "index.html"), resolve(dist, "index.html"));
  const summary = { edition_id: edition.edition.id, editions_in_index: entries.length, layout_version: LAYOUT_VERSION };
  const output = stringOption("output");
  if (output) {
    await mkdir(output, { recursive: true });
    await cp(dist, output, { recursive: true });
    await rm(work, { recursive: true, force: true });
    emit("preview", { status: "built", path: resolve(output), ...summary });
    return;
  }
  const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    let file = join(dist, decodeURIComponent(url.pathname));
    if (!file.startsWith(dist)) {
      response.writeHead(403).end();
      return;
    }
    try {
      if ((await stat(file)).isDirectory()) {
        if (!url.pathname.endsWith("/")) {
          response.writeHead(301, { location: `${url.pathname}/` }).end();
          return;
        }
        file = join(file, "index.html");
      }
      await stat(file);
    } catch {
      response.writeHead(404, { "content-type": "text/plain" }).end("not found");
      return;
    }
    response.writeHead(200, { "content-type": PREVIEW_TYPES[extname(file)] ?? "application/octet-stream" });
    createReadStream(file).pipe(response);
  });
  const port = integerOption("port", 4747, 1);
  await new Promise<void>((ok, bad) => server.once("error", bad).listen(port, "127.0.0.1", ok));
  const address = server.address();
  const bound = typeof address === "object" && address ? address.port : port;
  emit("preview", {
    status: "serving",
    url: `http://127.0.0.1:${bound}/`,
    edition_page: `http://127.0.0.1:${bound}/n/${edition.edition.id}/`,
    archive: `http://127.0.0.1:${bound}/archive/`,
    ...summary,
    stop: "Ctrl-C",
  });
  await new Promise<void>((done) => {
    const stop = () => server.close(() => done());
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  });
  await rm(work, { recursive: true, force: true });
}

async function buildWebAction(): Promise<void> {
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const dry = args.options.has("dry-run");
  const work = await mkdtemp(resolve(tmpdir(), "publisher-web-"));
  try {
    const layout = args.options.get("layout");
    if (layout !== undefined && layout !== "grid" && layout !== "sheet") {
      fail("usage_error", "--layout must be grid or sheet", { option: "layout", value: layout });
    }
    const dist = await buildWeb(root, work, edition, [indexEntry(edition, "skipped")], { layout: layout as never });
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

async function fit(): Promise<void> {
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const config = loadTitleConfig(resolve(root, "config/title.yaml"));
  const result = await withBrowser(root, (browser) => fitEdition(browser, edition, config));
  emit("fit", {
    status: "fit",
    edition_id: edition.edition.id,
    composition: result.plan.composition,
    plan: result.plan,
    fit_report: result.report,
  });
}

/** Fit, capture, and convert one edition into <output>/device/; never overwrites an existing page. */
async function renderDevice(): Promise<void> {
  const edition = await loadValidEdition(requiredOption(args, "edition"));
  const dry = args.options.has("dry-run");
  const output = dry ? null : resolve(requiredOption(args, "output"));
  const files = ["page-1.html", "page-1.png", "composition.json", "fit-report.json"];
  if (output) {
    for (const name of files) {
      if (await access(resolve(output, name)).then(() => true, () => false)) {
        fail("bundle_exists", "output directory already holds a device page", { path: resolve(output, name) });
      }
    }
  }
  const config = loadTitleConfig(resolve(root, "config/title.yaml"));
  const device = await buildDevice(root, edition, config);
  if (output) {
    await mkdir(output, { recursive: true });
    await writeFile(resolve(output, "page-1.html"), device.html);
    await writeFile(resolve(output, "page-1.png"), device.png);
    await writeFile(
      resolve(output, "composition.json"),
      canonical({
        schema_version: 1,
        edition_id: edition.edition.id,
        composition: device.plan.composition,
        stories: device.plan.placements,
        contract_sha256: hashBytes(canonical(edition)),
        config_sha256: await hashFile(resolve(root, "config/title.yaml")),
        assets_sha256: device.stylesheet_sha256,
      }),
    );
    await writeFile(resolve(output, "fit-report.json"), canonical(device.report));
  }
  emit("render-device", {
    status: dry ? "planned" : "rendered",
    edition_id: edition.edition.id,
    composition: device.plan.composition,
    story_ids: device.plan.placements.map((p) => p.story_id),
    omitted: device.plan.omitted,
    dropped_callouts: device.plan.dropped_callouts,
    image_sha256: device.image_sha256,
    files: output ? files.map((name) => resolve(output, name)) : [],
    environment: device.environment,
  });
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
    case "preview":
      return preview();
    case "fit":
      return fit();
    case "render-device":
      return renderDevice();
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
