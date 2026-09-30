// Section 13: immutable store, release shell, durable intent, atomic activation, recovery.
//
// Layout under <publish-root>:
//   store/n/<edition-id>/   immutable bundle, one rename, files 0444
//   store/a/<layout>/       immutable shared assets
//   releases/<release-id>/  complete docroot, hardlinks into store/
//   live -> releases/<id>   symlink; the docroot
//   state/pending.json      the one durable activation intent, or absent
//   state/activations/      retained activation records, numbered by sequence
//   .lock                   exclusive directory lock for publish and recover
//   .staging-<release-id>/  run-owned work; removed on success, kept only while an intent is pending

import {
  chmod,
  copyFile,
  cp,
  link,
  mkdir,
  open,
  readdir,
  readFile,
  lstat,
  readlink,
  rename,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import type { EditionContractV1 } from "../contract/edition-contract.generated.ts";
import { canonical, hashBytes, hashFile } from "./hash.ts";
import { publisherError } from "./errors.ts";
import {
  buildWeb,
  copyAssets,
  indexEntry,
  LAYOUT_VERSION,
  sortEntries,
  type IndexEntry,
} from "./web.ts";
import { loadTitleConfig } from "../contract/title-config.ts";
import {
  buildDevice,
  DEVICE_INTEGRITY_ERRORS,
  type DeviceOutput,
} from "../device/index.ts";

export type PublishOptions = {
  root: string;
  projectRoot: string;
  edition: EditionContractV1;
  dryRun: boolean;
  skipDevice: boolean;
  requireDevice: boolean;
  /** Releases to retain after activation, newest first by activation sequence. Minimum 1. */
  keepReleases?: number;
  /** Test hook: throw at a named protocol boundary. */
  crashAt?: "before-intent" | "after-intent" | "after-live";
};

type FileRecord = { path: string; bytes: number; sha256: string };

type Intent = {
  version: 1;
  release_id: string;
  edition_id: string;
  contract_sha256: string;
  manifest_sha256: string;
  predecessor: string | null;
  work: string;
  staged: { bundle: string; assets: string; release: string };
  final: { bundle: string; assets: string; release: string };
};

type Activation = Intent & {
  activated: true;
  sequence: number;
  activated_at: string;
};

type DeviceOutcome =
  | { status: "skipped" }
  | { status: "published"; output: DeviceOutput }
  | {
      status: "failed";
      error: {
        type: string;
        message: string;
        details: Record<string, unknown>;
      };
      report: unknown;
    };

const DEFAULT_KEEP_RELEASES = 5;

// ---------------------------------------------------------------------------------------------
// Filesystem helpers
// ---------------------------------------------------------------------------------------------

const exists = (path: string) =>
  stat(path)
    .then(() => true)
    .catch(() => false);

async function fsync(path: string): Promise<void> {
  const handle = await open(path, "r");
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function atomicJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temp = `${path}.tmp-${randomUUID()}`;
  await writeFile(temp, canonical(value));
  await fsync(temp);
  await rename(temp, path);
  await fsync(dirname(path));
}

async function listFiles(dir: string, prefix = ""): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const rel = join(prefix, entry.name);
    if (entry.isDirectory())
      out.push(...(await listFiles(join(dir, entry.name), rel)));
    else out.push(rel);
  }
  return out.sort();
}

async function listDirs(dir: string): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      const full = join(dir, entry.name);
      out.push(...(await listDirs(full)), full);
    }
  }
  return out;
}

/** Files 0444, directories 0555: an accidental-write guard, not protection against the owner. */
async function freeze(dir: string): Promise<void> {
  for (const file of await listFiles(dir)) await chmod(join(dir, file), 0o444);
  for (const sub of await listDirs(dir)) await chmod(sub, 0o555);
  await chmod(dir, 0o555);
}

async function thaw(dir: string): Promise<void> {
  if (!(await exists(dir))) return;
  for (const sub of await listDirs(dir)) await chmod(sub, 0o755);
  await chmod(dir, 0o755);
}

async function syncTree(dir: string): Promise<void> {
  for (const file of await listFiles(dir)) await fsync(join(dir, file));
  for (const sub of await listDirs(dir)) await fsync(sub);
  await fsync(dir);
}

async function hardlinkTree(source: string, dest: string): Promise<void> {
  await mkdir(dest, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    const from = join(source, entry.name);
    const to = join(dest, entry.name);
    if (entry.isDirectory()) await hardlinkTree(from, to);
    else await link(from, to);
  }
}

async function fileRecords(dir: string): Promise<FileRecord[]> {
  const records: FileRecord[] = [];
  for (const path of await listFiles(dir)) {
    const full = join(dir, path);
    records.push({
      path,
      bytes: (await stat(full)).size,
      sha256: await hashFile(full),
    });
  }
  return records;
}

async function verifyRecords(
  dir: string,
  records: FileRecord[],
  what: string,
): Promise<void> {
  for (const record of records) {
    const full = join(dir, record.path);
    if (!(await exists(full)) || (await hashFile(full)) !== record.sha256) {
      throw publisherError(
        "bundle_integrity_failed",
        `${what} does not match its recorded hash`,
        {
          path: record.path,
        },
      );
    }
  }
}

function contained(root: string, path: string): boolean {
  const rel = relative(root, resolve(root, path));
  return (
    rel !== "" &&
    rel !== ".." &&
    !rel.startsWith(`..${sep}`) &&
    !rel.includes("\0")
  );
}

// ---------------------------------------------------------------------------------------------
// Lock, probe, and state readers
// ---------------------------------------------------------------------------------------------

/** One exclusive lock for publish and recover, dry runs included. Never waits, never auto-breaks. */
async function withLock<T>(root: string, body: () => Promise<T>): Promise<T> {
  const path = join(root, ".lock");
  try {
    await mkdir(path);
  } catch {
    const ageSeconds = await stat(path)
      .then((s) => Math.round((Date.now() - s.mtimeMs) / 1000))
      .catch(() => null);
    throw publisherError(
      "lock_busy",
      "another publish or recover holds the publish-root lock",
      {
        lock: ".lock",
        age_seconds: ageSeconds,
      },
    );
  }
  try {
    return await body();
  } finally {
    await rm(path, { recursive: true, force: true });
  }
}

/** Store and releases must share one filesystem, because releases are hardlinks into the store. */
async function probeSameFilesystem(root: string): Promise<void> {
  const id = randomUUID();
  const source = join(root, "store", `.probe-${id}`);
  const target = join(root, "releases", `.probe-${id}`);
  await mkdir(dirname(source), { recursive: true });
  await mkdir(dirname(target), { recursive: true });
  try {
    await writeFile(source, "");
    await link(source, target);
  } catch (error) {
    throw publisherError(
      "publish_root_invalid",
      "store/ and releases/ must be on one filesystem that supports hard links",
      {
        cause: (error as Error).message,
      },
    );
  } finally {
    await rm(source, { force: true });
    await rm(target, { force: true });
  }
}

async function currentRelease(root: string): Promise<string | null> {
  try {
    return resolve(root, await readlink(join(root, "live")));
  } catch {
    return null;
  }
}

export async function currentIndex(root: string): Promise<IndexEntry[]> {
  const live = await currentRelease(root);
  if (!live) return [];
  return JSON.parse(await readFile(join(live, "index.json"), "utf8")).editions;
}

async function readPending(root: string): Promise<Intent | null> {
  const path = join(root, "state", "pending.json");
  if (!(await exists(path))) return null;
  return JSON.parse(await readFile(path, "utf8")) as Intent;
}

async function readActivations(root: string): Promise<Activation[]> {
  const dir = join(root, "state", "activations");
  if (!(await exists(dir))) return [];
  const records: Activation[] = [];
  for (const name of await readdir(dir)) {
    if (name.endsWith(".json"))
      records.push(JSON.parse(await readFile(join(dir, name), "utf8")));
  }
  return records.sort((a, b) => a.sequence - b.sequence);
}

function environment(
  packageJson: Record<string, any>,
  fontsLock: string,
  device: DeviceOutcome,
) {
  const magick = spawnSync("magick", ["-version"], { encoding: "utf8" });
  const imagemagick =
    magick.status === 0
      ? magick.stdout.split("\n")[0]!.replace(/^Version: ImageMagick /, "")
      : null;
  const chromium =
    device.status === "published" ? device.output.environment : null;
  const failures: Array<{ code: string; component: string }> = [];
  if (device.status === "failed")
    failures.push({ code: device.error.type, component: "device" });
  return {
    node: process.version,
    icu: process.versions.icu,
    astro: packageJson.dependencies.astro,
    playwright: packageJson.dependencies.playwright,
    chromium: chromium?.chromium ?? null,
    chromium_executable_sha256: chromium?.chromium_executable_sha256 ?? null,
    imagemagick,
    fonts_lock_sha256: fontsLock,
    failures,
  };
}

/**
 * The device edition, or the reason there is none. Capacity and availability failures degrade to a
 * web-only publication unless --require-device; integrity failures always stop the run.
 */
async function renderDevice(options: PublishOptions): Promise<DeviceOutcome> {
  if (options.skipDevice) return { status: "skipped" };
  const config = loadTitleConfig(
    join(options.projectRoot, "config/title.yaml"),
  );
  try {
    return {
      status: "published",
      output: await buildDevice(options.projectRoot, options.edition, config),
    };
  } catch (caught) {
    const error = caught as Error & {
      type?: string;
      details?: Record<string, unknown>;
    };
    if (
      !error.type ||
      options.requireDevice ||
      DEVICE_INTEGRITY_ERRORS.has(error.type)
    )
      throw caught;
    const { fit_report, ...details } = error.details ?? {};
    process.stderr.write(
      `device edition failed: ${error.type}: ${error.message}\n`,
    );
    return {
      status: "failed",
      error: { type: error.type, message: error.message, details },
      report: fit_report,
    };
  }
}

// ---------------------------------------------------------------------------------------------
// Activation, retention
// ---------------------------------------------------------------------------------------------

async function swapLive(root: string, intent: Intent): Promise<void> {
  const target = resolve(root, intent.final.release);
  const live = await currentRelease(root);
  if (live === target) return;
  const expected = intent.predecessor
    ? resolve(root, intent.predecessor)
    : null;
  if (live !== expected) {
    throw publisherError(
      "publish_conflict",
      "the live release is not the predecessor this run recorded",
      {
        expected: intent.predecessor,
        found: live ? relative(root, live) : null,
      },
    );
  }
  const temp = join(root, `.live-${intent.release_id}`);
  // The name carries the release id, so an existing entry is this run's own leftover from a crash
  // between creating it and renaming it; replace it. Anything that is not a symlink is not ours.
  const leftover = await lstat(temp).catch(() => null);
  if (leftover) {
    if (!leftover.isSymbolicLink()) {
      throw publisherError(
        "publish_conflict",
        "the temporary live link path is occupied by something else",
        { path: temp },
      );
    }
    await rm(temp);
  }
  await symlink(relative(root, target), temp);
  await rename(temp, join(root, "live"));
  await fsync(root);
}

async function recordActivation(
  root: string,
  intent: Intent,
): Promise<Activation> {
  const existing = await readActivations(root);
  const already = existing.find((a) => a.release_id === intent.release_id);
  if (already) {
    // A crash between writing the record and clearing the intent lands here: finish the clean-up.
    if (
      already.manifest_sha256 !== intent.manifest_sha256 ||
      already.edition_id !== intent.edition_id
    ) {
      throw publisherError(
        "publish_conflict",
        "an activation record exists for this release but describes a different publication",
        {
          release_id: intent.release_id,
        },
      );
    }
    await rm(join(root, "state", "pending.json"), { force: true });
    await fsync(join(root, "state"));
    return already;
  }
  const sequence = (existing.at(-1)?.sequence ?? 0) + 1;
  const record: Activation = {
    ...intent,
    activated: true,
    sequence,
    activated_at: new Date().toISOString(),
  };
  await atomicJson(
    join(root, "state", "activations", `${intent.release_id}.json`),
    record,
  );
  await rm(join(root, "state", "pending.json"), { force: true });
  await fsync(join(root, "state"));
  return record;
}

/** Delete releases beyond the newest `keep` by activation sequence. Never the live target. Best effort. */
async function retainReleases(root: string, keep: number): Promise<string[]> {
  const warnings: string[] = [];
  const live = await currentRelease(root);
  const records = await readActivations(root);
  const doomed = records.slice(
    0,
    Math.max(0, records.length - Math.max(1, keep)),
  );
  for (const record of doomed) {
    const dir = resolve(root, record.final.release);
    if (dir === live || !(await exists(dir))) continue;
    try {
      await thaw(dir);
      await rm(dir, { recursive: true, force: true });
    } catch (error) {
      warnings.push(
        `retention: could not remove ${record.final.release}: ${(error as Error).message}`,
      );
    }
  }
  return warnings;
}

// ---------------------------------------------------------------------------------------------
// publish
// ---------------------------------------------------------------------------------------------

export async function publishEdition(
  options: PublishOptions,
): Promise<Record<string, unknown>> {
  const { root, projectRoot, edition, dryRun } = options;
  const editionId = edition.edition.id;
  const contract = canonical(edition);
  const contractDigest = hashBytes(contract);
  const keep = options.keepReleases ?? DEFAULT_KEEP_RELEASES;

  await mkdir(root, { recursive: true });
  return withLock(root, async () => {
    await probeSameFilesystem(root);
    if (await readPending(root)) {
      throw publisherError(
        "recovery_required",
        "a pending activation exists; run recover first",
        {},
      );
    }

    const releaseBefore = await currentRelease(root);
    const priorEntries = await currentIndex(root);
    const finalBundle = join(root, "store", "n", editionId);
    const finalAssets = join(root, "store", "a", LAYOUT_VERSION);

    if (await exists(finalBundle)) {
      const prior = JSON.parse(
        await readFile(join(finalBundle, "manifest.json"), "utf8"),
      );
      if (prior.contract_sha256 === contractDigest) {
        throw publisherError(
          "bundle_exists",
          "edition id was already published",
          { edition_id: editionId },
        );
      }
      throw publisherError(
        "publish_conflict",
        "edition id exists with different bytes",
        { edition_id: editionId },
      );
    }

    const releaseId = `release-${editionId}-${randomUUID()}`;
    const work = join(root, `.staging-${releaseId}`);
    let intentDurable = false;
    try {
      await mkdir(work, { recursive: true });
      const device = await renderDevice(options);
      const entries = sortEntries([
        ...priorEntries,
        indexEntry(edition, device.status),
      ]);
      const latest = entries.at(-1)!;
      const latestDevice =
        entries.filter((e) => e.device_status === "published").at(-1) ?? null;

      // Web build and bundle.
      const dist = await buildWeb(projectRoot, work, edition, entries);
      const bundle = join(work, "bundle");
      await mkdir(bundle, { recursive: true });
      await writeFile(join(bundle, "edition.json"), contract);
      await copyFile(
        join(dist, "n", editionId, "index.html"),
        join(bundle, "index.html"),
      );
      if (device.status === "published") {
        const { output } = device;
        await mkdir(join(bundle, "device"), { recursive: true });
        await writeFile(join(bundle, "device", "page-1.html"), output.html);
        await writeFile(join(bundle, "device", "page-1.png"), output.png);
        await writeFile(
          join(bundle, "fit-report.json"),
          canonical(output.report),
        );
        await writeFile(
          join(bundle, "composition.json"),
          canonical({
            schema_version: 1,
            edition_id: editionId,
            composition: output.plan.composition,
            stories: output.plan.placements,
            contract_sha256: contractDigest,
            config_sha256: await hashFile(
              join(projectRoot, "config/title.yaml"),
            ),
            assets_sha256: output.stylesheet_sha256,
          }),
        );
      } else if (device.status === "failed" && device.report) {
        await writeFile(
          join(bundle, "fit-report.json"),
          canonical(device.report),
        );
      }
      const receiptDevice =
        device.status === "published"
          ? {
              status: "published",
              composition: device.output.plan.composition,
              story_ids: device.output.plan.placements.map((p) => p.story_id),
              placements: device.output.plan.placements,
              omitted: device.output.plan.omitted,
              dropped_callouts: device.output.plan.dropped_callouts,
              structural_elements: [],
            }
          : {
              status: device.status,
              story_ids: [],
              omitted: edition.stories.map((s) => ({
                story_id: s.id,
                reason: `device_${device.status}`,
              })),
              dropped_callouts: [],
              structural_elements: [],
              ...(device.status === "failed"
                ? {
                    error: {
                      type: device.error.type,
                      message: device.error.message,
                    },
                  }
                : {}),
            };
      const receipt = {
        schema_version: 1,
        edition_id: editionId,
        web: { story_ids: edition.stories.map((s) => s.id) },
        device: receiptDevice,
        bundle: { path: `n/${editionId}/` },
      };
      await writeFile(
        join(bundle, "publication-receipt.json"),
        canonical(receipt),
      );

      // Shared assets.
      const assets = join(work, "assets");
      await copyAssets(projectRoot, assets);
      const assetRecords = await fileRecords(assets);
      if (await exists(finalAssets))
        await verifyRecords(finalAssets, assetRecords, "shared asset").catch(
          (error) => {
            throw publisherError(
              "asset_version_conflict",
              "layout version already exists with different assets",
              error.details,
            );
          },
        );

      // Manifest (hashes the receipt; never hashes itself).
      const packageJson = JSON.parse(
        await readFile(join(projectRoot, "package.json"), "utf8"),
      );
      const manifest = {
        schema_version: 1,
        edition_id: editionId,
        layout_version: LAYOUT_VERSION,
        contract_sha256: contractDigest,
        config_sha256: await hashFile(join(projectRoot, "config/title.yaml")),
        files: await fileRecords(bundle),
        shared_assets: { path: `a/${LAYOUT_VERSION}/`, files: assetRecords },
        device:
          device.status === "published"
            ? {
                status: "published",
                composition: device.output.plan.composition,
                image_sha256: device.output.image_sha256,
              }
            : device.status === "failed"
              ? { status: "failed", error_type: device.error.type }
              : { status: "skipped" },
        environment: environment(
          packageJson,
          await hashFile(join(projectRoot, "assets/fonts/fonts.lock.json")),
          device,
        ),
      };
      await writeFile(join(bundle, "manifest.json"), canonical(manifest));
      const manifestDigest = await hashFile(join(bundle, "manifest.json"));

      // Release shell: everything Astro emitted except n/, plus hardlinks for every edition and asset.
      const release = join(work, "release");
      await cp(dist, release, { recursive: true });
      await rm(join(release, "n"), { recursive: true, force: true });
      for (const entry of priorEntries)
        await hardlinkTree(
          join(root, "store", "n", entry.id),
          join(release, "n", entry.id),
        );
      await hardlinkTree(bundle, join(release, "n", editionId));
      await hardlinkTree(
        (await exists(finalAssets)) ? finalAssets : assets,
        join(release, "a", LAYOUT_VERSION),
      );
      // Archived editions link the layout version they were published with, so every version the
      // store holds rides along in the release.
      const assetRoot = join(root, "store", "a");
      if (await exists(assetRoot)) {
        for (const version of await readdir(assetRoot)) {
          if (version !== LAYOUT_VERSION && !version.startsWith("."))
            await hardlinkTree(
              join(assetRoot, version),
              join(release, "a", version),
            );
        }
      }
      await writeFile(
        join(release, "index.json"),
        canonical({ editions: entries }),
      );
      await writeFile(
        join(release, "latest.json"),
        canonical({
          web: {
            edition_id: latest.id,
            date: latest.date,
            name: latest.name,
            status: "published",
          },
          device: latestDevice
            ? {
                edition_id: latestDevice.id,
                date: latestDevice.date,
                status: "published",
              }
            : { edition_id: null, date: null, status: "none" },
        }),
      );
      // device/current.png follows the newest edition with a device page, which may not be this one.
      if (latestDevice) {
        await mkdir(join(release, "device"), { recursive: true });
        const current =
          latestDevice.id === editionId
            ? join(bundle, "device", "page-1.png")
            : join(root, "store", "n", latestDevice.id, "device", "page-1.png");
        await link(current, join(release, "device", "current.png"));
      }
      // "/" is the latest edition's own immutable page, which may be an older edition on a backdated run.
      await rm(join(release, "index.html"), { force: true });
      const latestPage =
        latest.id === editionId
          ? join(bundle, "index.html")
          : join(root, "store", "n", latest.id, "index.html");
      await link(latestPage, join(release, "index.html"));

      if (dryRun) {
        return {
          status: "planned",
          edition_id: editionId,
          device_status: device.status,
          bundle: { path: `n/${editionId}/`, manifest_sha256: manifestDigest },
          live_target: `releases/${releaseId}`,
        };
      }

      // Durable intent.
      await syncTree(work);
      if (options.crashAt === "before-intent") {
        throw publisherError(
          "publication_outcome_uncertain",
          "injected crash",
          { durable_intent: false },
        );
      }
      const intent: Intent = {
        version: 1,
        release_id: releaseId,
        edition_id: editionId,
        contract_sha256: contractDigest,
        manifest_sha256: manifestDigest,
        predecessor: releaseBefore ? relative(root, releaseBefore) : null,
        work: relative(root, work),
        staged: {
          bundle: relative(root, bundle),
          assets: relative(root, assets),
          release: relative(root, release),
        },
        final: {
          bundle: relative(root, finalBundle),
          assets: relative(root, finalAssets),
          release: `releases/${releaseId}`,
        },
      };
      await atomicJson(join(root, "state", "pending.json"), intent);
      intentDurable = true;
      if (options.crashAt === "after-intent") {
        throw publisherError(
          "publication_outcome_uncertain",
          "injected crash",
          { durable_intent: true },
        );
      }

      // Promotion, activation, acknowledgment.
      await promote(root, intent);
      await swapLive(root, intent);
      if (options.crashAt === "after-live") {
        throw publisherError(
          "publication_outcome_uncertain",
          "injected crash",
          { durable_intent: true, live: true },
        );
      }
      await recordActivation(root, intent);
      await rm(work, { recursive: true, force: true });
      intentDurable = false;
      const warnings = await retainReleases(root, keep);
      return {
        status: device.status === "failed" ? "partial" : "published",
        edition_id: editionId,
        web_story_ids: receipt.web.story_ids,
        device_status: device.status,
        device:
          device.status === "published"
            ? {
                composition: device.output.plan.composition,
                story_ids: device.output.plan.placements.map((p) => p.story_id),
                image_sha256: device.output.image_sha256,
              }
            : device.status === "failed"
              ? { error: device.error }
              : null,
        bundle: { path: `n/${editionId}/`, manifest_sha256: manifestDigest },
        warnings,
      };
    } finally {
      // Before the intent is durable, only run-owned staging exists and it is cleaned. After, it is
      // recovery material and stays until recover finishes.
      if (!intentDurable) await rm(work, { recursive: true, force: true });
    }
  });
}

/** Rename each staged object to its final immutable path, skipping ones already promoted. */
async function promote(root: string, intent: Intent): Promise<void> {
  for (const key of ["assets", "bundle", "release"] as const) {
    const staged = resolve(root, intent.staged[key]);
    const final = resolve(root, intent.final[key]);
    if (await exists(final)) continue;
    await mkdir(dirname(final), { recursive: true });
    await rename(staged, final);
    await fsync(dirname(final));
    await freeze(final);
  }
}

// ---------------------------------------------------------------------------------------------
// recover
// ---------------------------------------------------------------------------------------------

export async function recoverPublication(
  root: string,
  dryRun: boolean,
): Promise<Record<string, unknown>> {
  return withLock(root, async () => {
    const intent = await readPending(root);
    if (!intent) return { status: "nothing_to_recover" };

    for (const path of [
      intent.work,
      ...Object.values(intent.staged),
      ...Object.values(intent.final),
    ]) {
      if (!contained(root, path)) {
        throw publisherError(
          "publish_conflict",
          "intent names a path outside the publish root",
          { path },
        );
      }
    }

    // Verify every object, staged or already promoted, against the hashes the intent recorded.
    const locate = async (key: keyof Intent["staged"]) => {
      const final = resolve(root, intent.final[key]);
      if (await exists(final)) return { path: final, promoted: true };
      const staged = resolve(root, intent.staged[key]);
      if (await exists(staged)) return { path: staged, promoted: false };
      throw publisherError(
        "bundle_integrity_failed",
        `neither staged nor final ${key} exists`,
        { key },
      );
    };
    const bundle = await locate("bundle");
    const assets = await locate("assets");
    const release = await locate("release");
    const manifestPath = join(bundle.path, "manifest.json");
    if (
      !(await exists(manifestPath)) ||
      (await hashFile(manifestPath)) !== intent.manifest_sha256
    ) {
      throw publisherError(
        "bundle_integrity_failed",
        "manifest does not match the intent",
        {},
      );
    }
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    if (manifest.contract_sha256 !== intent.contract_sha256) {
      throw publisherError(
        "bundle_integrity_failed",
        "contract digest does not match the intent",
        {},
      );
    }
    await verifyRecords(bundle.path, manifest.files, "bundle file");
    await verifyRecords(
      assets.path,
      manifest.shared_assets.files,
      "shared asset",
    );
    const releaseManifest = join(
      release.path,
      "n",
      intent.edition_id,
      "manifest.json",
    );
    if (
      !(await exists(releaseManifest)) ||
      (await hashFile(releaseManifest)) !== intent.manifest_sha256
    ) {
      throw publisherError(
        "bundle_integrity_failed",
        "staged release does not carry the intended bundle",
        {},
      );
    }

    const live = await currentRelease(root);
    const plan = {
      edition_id: intent.edition_id,
      release_id: intent.release_id,
      promote: (["bundle", "assets", "release"] as const).filter(
        (k) => !{ bundle, assets, release }[k].promoted,
      ),
      swap_live: live !== resolve(root, intent.final.release),
    };
    if (dryRun) return { status: "planned", ...plan };

    await promote(root, intent);
    await swapLive(root, intent);
    const record = await recordActivation(root, intent);
    await rm(resolve(root, intent.work), { recursive: true, force: true });
    const warnings = await retainReleases(root, DEFAULT_KEEP_RELEASES);
    return {
      status: "recovered",
      edition_id: intent.edition_id,
      manifest_sha256: intent.manifest_sha256,
      sequence: record.sequence,
      warnings,
    };
  });
}

// ---------------------------------------------------------------------------------------------
// receipt, verify
// ---------------------------------------------------------------------------------------------

export async function activatedReceipt(
  root: string,
  editionId: string,
): Promise<Record<string, unknown>> {
  const pending = await readPending(root);
  if (pending?.edition_id === editionId) {
    throw publisherError(
      "recovery_required",
      "this edition has a pending activation; run recover",
      {
        edition_id: editionId,
      },
    );
  }
  const activation = (await readActivations(root)).find(
    (a) => a.edition_id === editionId,
  );
  const bundle = join(root, "store", "n", editionId);
  if (!activation) {
    if (await exists(bundle)) {
      throw publisherError(
        "edition_not_activated",
        "the bundle is stored but was never activated",
        {
          edition_id: editionId,
        },
      );
    }
    throw publisherError("resource_not_found", "no such edition", {
      edition_id: editionId,
    });
  }
  await expectManifest(bundle, activation);
  const receipt = JSON.parse(
    await readFile(join(bundle, "publication-receipt.json"), "utf8"),
  );
  return {
    receipt,
    manifest_sha256: await hashFile(join(bundle, "manifest.json")),
    activated: true,
    activation: {
      release_id: activation.release_id,
      sequence: activation.sequence,
    },
  };
}

/** The manifest is trusted only if it is the one the activation record hashed at publication. */
async function expectManifest(
  bundle: string,
  activation: Activation,
): Promise<void> {
  const path = join(bundle, "manifest.json");
  const actual = (await exists(path)) ? await hashFile(path) : null;
  if (actual !== activation.manifest_sha256) {
    throw publisherError(
      "bundle_integrity_failed",
      "the manifest is not the one recorded at activation",
      {
        edition_id: activation.edition_id,
        expected: activation.manifest_sha256,
        actual,
      },
    );
  }
}

export async function verifyBundle(
  root: string,
  editionId: string,
): Promise<Record<string, unknown>> {
  const bundle = join(root, "store", "n", editionId);
  if (!(await exists(bundle))) {
    throw publisherError("resource_not_found", "bundle not found", {
      edition_id: editionId,
    });
  }
  const activation = (await readActivations(root)).find(
    (a) => a.edition_id === editionId,
  );
  if (activation) await expectManifest(bundle, activation);
  const manifest = JSON.parse(
    await readFile(join(bundle, "manifest.json"), "utf8"),
  );
  await verifyRecords(bundle, manifest.files, "bundle file");
  await verifyRecords(
    join(root, "store", manifest.shared_assets.path),
    manifest.shared_assets.files,
    "shared asset",
  );
  return {
    valid: true,
    edition_id: editionId,
    manifest_sha256: await hashFile(join(bundle, "manifest.json")),
  };
}
