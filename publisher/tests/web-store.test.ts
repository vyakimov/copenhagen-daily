import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  readlink,
  rm,
  stat,
} from "node:fs/promises";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import {
  readEdition,
  validateEdition,
} from "../src/contract/edition-contract.ts";
import {
  publishEdition,
  recoverPublication,
  activatedReceipt,
  verifyBundle,
} from "../src/publish/store.ts";
import { hashFile } from "../src/publish/hash.ts";
import { buildWeb, indexEntry, LAYOUT_VERSION } from "../src/publish/web.ts";

const projectRoot = resolve(import.meta.dirname, "..");
const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

async function edition(name: string) {
  const checked = validateEdition(
    await readEdition(resolve(projectRoot, "contracts/examples", name)),
  );
  assert.equal(checked.valid, true);
  if (!checked.valid) throw new Error("unreachable");
  return checked.value;
}

/** A hash of every file and symlink under root, so two trees can be compared byte for byte. */
async function tree(root: string): Promise<string> {
  const walk = async (dir: string, prefix = ""): Promise<string[]> => {
    const out: string[] = [];
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const rel = join(prefix, entry.name);
      const full = join(dir, entry.name);
      if (entry.isDirectory()) out.push(...(await walk(full, rel)));
      else if (entry.isSymbolicLink())
        out.push(`${rel}:link:${await readlink(full)}`);
      else out.push(`${rel}:${await hashFile(full)}`);
    }
    return out.sort();
  };
  return JSON.stringify(await walk(root));
}

async function htmlFiles(dir: string): Promise<string[]> {
  const out: string[] = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await htmlFiles(full)));
    else if (entry.name.endsWith(".html")) out.push(full);
  }
  return out;
}

const publish = (
  root: string,
  doc: any,
  extra: Partial<Parameters<typeof publishEdition>[0]> = {},
) =>
  publishEdition({
    root,
    projectRoot,
    edition: doc,
    dryRun: false,
    skipDevice: true,
    requireDevice: false,
    ...extra,
  });

test("web publication is immutable, hardlinked, verifiable, and backdate safe", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-store-"));
  const dense = await edition("dense.json");
  const first = await publish(root, dense);
  assert.equal(first.status, "published");

  // Every story and callout, at full length, in the reader-facing page.
  const html = await readFile(
    join(root, "live", "n", dense.edition.id, "index.html"),
    "utf8",
  );
  for (const story of dense.stories) {
    assert.match(html, new RegExp(story.id));
    assert.match(
      html.replaceAll("\u00ad", ""),
      new RegExp(escapeRegExp(story.copy.headline)),
    );
    for (const c of story.callouts as any[]) {
      assert.match(
        html.replaceAll("\u00ad", ""),
        new RegExp(
          escapeRegExp(String(c.text ?? c.value ?? c.title ?? c.label)),
        ),
      );
    }
  }
  // Body copy carries build-time soft hyphens; the stored contract never does.
  assert.ok(html.includes("\u00ad"));
  assert.ok(
    !(
      await readFile(
        join(root, "store", "n", dense.edition.id, "edition.json"),
        "utf8",
      )
    ).includes("\u00ad"),
  );
  // Timestamps are formatted for readers, never raw ISO.
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z<\//);
  assert.match(html, /Wednesday edition[\s\S]*News through 5am, 9 September/);

  // Store and release share inodes, files are read-only, and the manifest verifies.
  const stored = join(root, "store", "n", dense.edition.id, "index.html");
  const live = join(root, "live", "n", dense.edition.id, "index.html");
  assert.equal((await stat(stored)).ino, (await stat(live)).ino);
  assert.equal((await stat(stored)).mode & 0o777, 0o444);
  assert.equal((await verifyBundle(root, dense.edition.id)).valid, true);
  assert.deepEqual(
    await readdir(root).then((n) => n.filter((x) => x.startsWith(".staging"))),
    [],
  );

  // Repeated id, conflicting bytes.
  await assert.rejects(
    () => publish(root, dense),
    (e: any) => e.type === "bundle_exists",
  );
  const changed = structuredClone(dense);
  changed.stories[0]!.copy.headline += " changed";
  await assert.rejects(
    () => publish(root, changed),
    (e: any) => e.type === "publish_conflict",
  );

  // A dry run leaves the publish root byte-identical.
  const before = await tree(root);
  const sparse = await edition("sparse.json");
  const planned = await publish(root, sparse, { dryRun: true });
  assert.equal(planned.status, "planned");
  assert.equal(await tree(root), before);

  // A backdated edition enters the archive without moving latest backwards.
  const minimal = await edition("minimal.json");
  await publish(root, minimal);
  const latest = JSON.parse(
    await readFile(join(root, "live", "latest.json"), "utf8"),
  );
  assert.equal(latest.web.edition_id, dense.edition.id);
  assert.equal(latest.device.edition_id, null);
  const receipt = await activatedReceipt(root, minimal.edition.id);
  assert.equal(receipt.activated, true);
  await assert.rejects(
    () => activatedReceipt(root, "unknown-id"),
    (e: any) => e.type === "resource_not_found",
  );
});

test("durable intent recovers after the intent and after the live swap, with hashes verified", async () => {
  for (const crashAt of ["after-intent", "after-live"] as const) {
    const root = await mkdtemp(join(tmpdir(), "publish-recover-"));
    const doc = await edition("sparse.json");
    await assert.rejects(
      () => publish(root, doc, { crashAt }),
      (e: any) => e.type === "publication_outcome_uncertain",
    );
    await assert.rejects(
      () => publish(root, doc),
      (e: any) => e.type === "recovery_required",
    );
    await assert.rejects(
      () => activatedReceipt(root, doc.edition.id),
      (e: any) => e.type === "recovery_required",
    );
    const dry = await recoverPublication(root, true);
    assert.equal(dry.status, "planned");
    const recovered = await recoverPublication(root, false);
    assert.equal(recovered.status, "recovered");
    assert.equal(
      (await activatedReceipt(root, doc.edition.id)).activated,
      true,
    );
    assert.deepEqual(
      await readdir(root).then((n) =>
        n.filter((x) => x.startsWith(".staging")),
      ),
      [],
    );
    assert.equal(
      await recoverPublication(root, false).then((r) => r.status),
      "nothing_to_recover",
    );
  }
});

test("a crash before the intent leaves nothing behind, and a held lock is reported with its age", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-preintent-"));
  const doc = await edition("sparse.json");
  await assert.rejects(() => publish(root, doc, { crashAt: "before-intent" }));
  assert.equal(
    (await recoverPublication(root, false)).status,
    "nothing_to_recover",
  );
  assert.deepEqual(
    await readdir(root).then((n) => n.filter((x) => x.startsWith(".staging"))),
    [],
  );
  await mkdir(join(root, ".lock"), { recursive: true });
  await assert.rejects(
    () => publish(root, doc),
    (e: any) =>
      e.type === "lock_busy" && typeof e.details.age_seconds === "number",
  );
  await rm(join(root, ".lock"), { recursive: true });
});

test("retention keeps the newest releases by activation sequence and never the live one", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-retention-"));
  for (const name of ["minimal.json", "dense.json", "sparse.json"])
    await publish(root, await edition(name), { keepReleases: 1 });
  const releases = await readdir(join(root, "releases"));
  assert.equal(releases.length, 1);
  assert.equal(await readlink(join(root, "live")), `releases/${releases[0]}`);
  // Store and activation records are untouched by retention.
  assert.equal((await readdir(join(root, "store", "n"))).length, 3);
  assert.equal((await readdir(join(root, "state", "activations"))).length, 3);
  assert.equal((await verifyBundle(root, "2026-09-08-morning")).valid, true);
});

test("the other composition builds from the same story markup", async () => {
  const dense = await edition("dense.json");
  const work = await mkdtemp(join(tmpdir(), "publisher-layout-"));
  const dist = await buildWeb(
    projectRoot,
    work,
    dense,
    [indexEntry(dense, "skipped")],
    { layout: "sheet" },
  );
  const html = await readFile(
    join(dist, "n", dense.edition.id, "index.html"),
    "utf8",
  );
  assert.match(html, /class="page layout-sheet"/);
  assert.match(html, /class="sheet"/);
  for (const story of dense.stories) assert.match(html, new RegExp(story.id));
});

test("wire copy is credited to its agency and links to its carrier", async () => {
  const wire = await edition("wire.json");
  const work = await mkdtemp(join(tmpdir(), "publisher-wire-"));
  const dist = await buildWeb(projectRoot, work, wire, [indexEntry(wire, "skipped")]);
  const html = await readFile(join(dist, "n", wire.edition.id, "index.html"), "utf8");
  const primary = wire.stories[0]!.sources[0]!;
  assert.match(html, new RegExp(`<h1[^>]*><a href="${escapeRegExp(primary.url)}"`));
  assert.match(primary.url, /kristeligt-dagblad\.dk/);
  // The source line credits the agency once, first, and no longer names the carrier on its own.
  assert.match(html, /<span class="pubs"[^>]*>Ritzau · DR · Berlingske · Jyllands-Posten · TV 2 · Politiken<\/span>/);
  // The evidence list names the agency and the outlet whose page the link opens.
  assert.match(html, /<span[^>]*>Ritzau via Kristeligt Dagblad, /);
  assert.match(html, /quoted by Ritzau/);
  // The dateline counts the agency, not the carrier.
  assert.doesNotMatch(html.replace(/Ritzau via Kristeligt Dagblad/g, ""), /Kristeligt Dagblad/);
});

test("standalone web builds are deterministic and load no remote resources", async () => {
  const work = await mkdtemp(join(tmpdir(), "publisher-determinism-"));
  const wrapper = resolve(projectRoot, "publish_news.sh");
  const editionPath = resolve(
    projectRoot,
    "contracts/examples/all-callout-kinds.json",
  );
  for (const name of ["one", "two"]) {
    const r = spawnSync(
      wrapper,
      ["build-web", "--edition", editionPath, "--output", join(work, name)],
      {
        cwd: "/tmp",
        encoding: "utf8",
      },
    );
    assert.equal(r.status, 0, r.stdout);
  }
  assert.equal(await tree(join(work, "one")), await tree(join(work, "two")));
  for (const file of await htmlFiles(join(work, "one"))) {
    const html = await readFile(file, "utf8");
    assert.doesNotMatch(html, /<script\b/i);
    for (const m of html.matchAll(/\b(?:src|href)="([^"]+)"/g)) {
      const url = m[1]!;
      assert.ok(
        url.startsWith("/") ||
          url.startsWith("./") ||
          url.startsWith("https://") ||
          url.startsWith("mailto:"),
        url,
      );
      if (url.startsWith("https://")) assert.match(m[0], /^href=/);
    }
  }
});

test("a release carries every layout version the store holds, so archived pages keep their stylesheet", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-assets-"));
  const older = join(root, "store", "a", "broadsheet-v0");
  await mkdir(older, { recursive: true });
  const { writeFile } = await import("node:fs/promises");
  await writeFile(join(older, "web.css"), "body{}\n");
  const doc = await edition("minimal.json");
  const result = await publish(root, doc);
  assert.equal(result.status, "published");
  assert.equal(
    await readFile(join(root, "live", "a", "broadsheet-v0", "web.css"), "utf8"),
    "body{}\n",
  );
  const html = await readFile(
    join(root, "live", "n", doc.edition.id, "index.html"),
    "utf8",
  );
  assert.match(html, /href="\/a\/broadsheet-v5\/web.css"/);
});

test("the archive is a month-grouped register that names the latest edition", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-archive-"));
  const doc = await edition("minimal.json");
  const result = await publish(root, doc);
  assert.equal(result.status, "published");
  const archive = await readFile(
    join(root, "live", "archive", "index.html"),
    "utf8",
  );
  assert.match(archive, /class="register"/);
  assert.match(archive, /class="register-month"/);
  assert.match(archive, /class="latest"/);
  assert.match(archive, new RegExp(`No\\. ${doc.edition.number}<`));
  const index = JSON.parse(
    await readFile(join(root, "live", "index.json"), "utf8"),
  );
  assert.equal(index.editions.at(-1).number, doc.edition.number);
  assert.match(
    archive,
    new RegExp(`href="/n/${escapeRegExp(doc.edition.id)}/"`),
  );
});

test("the flow is three build-time stacks, not balanced CSS columns", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-columns-"));
  const doc = await edition("dense.json");
  const result = await publish(root, doc);
  assert.equal(result.status, "published");
  const html = await readFile(
    join(root, "live", "n", doc.edition.id, "index.html"),
    "utf8",
  );
  assert.equal((html.match(/class="col"/g) ?? []).length, 3);
  const css = await readFile(
    join(root, "live", "a", "broadsheet-v5", "web.css"),
    "utf8",
  );
  assert.doesNotMatch(css, /\.flow\{[^}]*column-count/);
});

test("preview builds any edition against the store's real index without writing to the store", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-preview-"));
  const published = await edition("minimal.json");
  assert.equal((await publish(root, published)).status, "published");
  const before = await tree(root);
  const out = await mkdtemp(join(tmpdir(), "preview-out-"));
  const draft = await edition("dense.json");
  const r = spawnSync(
    resolve(projectRoot, "publish_news.sh"),
    [
      "preview",
      "--edition",
      resolve(projectRoot, "contracts/examples/dense.json"),
      "--publish-root",
      root,
      "--output",
      out,
    ],
    { encoding: "utf8" },
  );
  const envelope = JSON.parse(r.stdout);
  assert.equal(envelope.ok, true, r.stderr);
  assert.equal(envelope.result.status, "built");
  assert.equal(envelope.result.editions_in_index, 2);
  const page = await readFile(
    join(out, "n", draft.edition.id, "index.html"),
    "utf8",
  );
  assert.match(page, new RegExp(`href="/a/${LAYOUT_VERSION}/web.css"`));
  const archive = await readFile(join(out, "archive", "index.html"), "utf8");
  assert.match(
    archive,
    new RegExp(`href="/n/${escapeRegExp(published.edition.id)}/"`),
  );
  assert.match(
    archive,
    new RegExp(`href="/n/${escapeRegExp(draft.edition.id)}/"`),
  );
  assert.ok((await stat(join(out, "a", LAYOUT_VERSION, "web.css"))).isFile());
  assert.equal(
    await readFile(join(out, "index.html"), "utf8"),
    page,
    "the home page is the previewed edition",
  );
  assert.equal(await tree(root), before, "preview must not touch the store");
});

test("recovery clears a pending intent whose activation record was already written", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-pending-"));
  const doc = await edition("sparse.json");
  assert.equal((await publish(root, doc)).status, "published");
  const dir = join(root, "state", "activations");
  const [name] = await readdir(dir);
  const record = JSON.parse(await readFile(join(dir, name!), "utf8"));
  const { activated, sequence, activated_at, ...intent } = record;
  void activated;
  void activated_at;
  const { writeFile } = await import("node:fs/promises");
  await writeFile(join(root, "state", "pending.json"), JSON.stringify(intent));
  await assert.rejects(
    () => activatedReceipt(root, doc.edition.id),
    (e: any) => e.type === "recovery_required",
  );
  const first = await recoverPublication(root, false);
  assert.equal(first.status, "recovered");
  assert.equal(
    await stat(join(root, "state", "pending.json")).then(
      () => true,
      () => false,
    ),
    false,
    "the intent must be cleared",
  );
  assert.deepEqual(await readdir(dir), [name], "no second activation record");
  assert.equal(
    JSON.parse(await readFile(join(dir, name!), "utf8")).sequence,
    sequence,
  );
  assert.equal((await activatedReceipt(root, doc.edition.id)).activated, true);
  assert.equal(
    (await recoverPublication(root, false)).status,
    "nothing_to_recover",
  );
  const next = await edition("minimal.json");
  assert.equal((await publish(root, next)).status, "published");
});

test("recovery survives a crash between creating the temporary live link and renaming it", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-templink-"));
  const doc = await edition("sparse.json");
  await assert.rejects(
    () => publish(root, doc, { crashAt: "after-intent" }),
    (e: any) => e.type === "publication_outcome_uncertain",
  );
  const intent = JSON.parse(
    await readFile(join(root, "state", "pending.json"), "utf8"),
  );
  const { symlink } = await import("node:fs/promises");
  const { relative } = await import("node:path");
  await symlink(
    relative(root, resolve(root, intent.final.release)),
    join(root, `.live-${intent.release_id}`),
  );
  const recovered = await recoverPublication(root, false);
  assert.equal(recovered.status, "recovered");
  assert.equal(
    await readlink(join(root, "live")),
    relative(root, resolve(root, intent.final.release)),
  );
  assert.deepEqual(
    (await readdir(root)).filter((n) => n.startsWith(".live-")),
    [],
  );
  assert.equal((await activatedReceipt(root, doc.edition.id)).activated, true);
});

test("verify and receipt reject a bundle whose manifest no longer matches its activation record", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-tamper-"));
  const doc = await edition("sparse.json");
  assert.equal((await publish(root, doc)).status, "published");
  assert.equal((await verifyBundle(root, doc.edition.id)).valid, true);
  const bundle = join(root, "store", "n", doc.edition.id);
  const { chmod, writeFile } = await import("node:fs/promises");
  const manifestPath = join(bundle, "manifest.json");
  await chmod(bundle, 0o755);
  await chmod(manifestPath, 0o644);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.files = [];
  await writeFile(manifestPath, JSON.stringify(manifest));
  await assert.rejects(
    () => verifyBundle(root, doc.edition.id),
    (e: any) => e.type === "bundle_integrity_failed",
  );
  await assert.rejects(
    () => activatedReceipt(root, doc.edition.id),
    (e: any) => e.type === "bundle_integrity_failed",
  );
});

test("the web edition does not link to the device page", async () => {
  const work = await mkdtemp(join(tmpdir(), "publish-devicelink-"));
  const doc = await edition("minimal.json");
  const dist = await buildWeb(projectRoot, work, doc, [indexEntry(doc, "published")]);
  const page = await readFile(join(dist, "n", doc.edition.id, "index.html"), "utf8");
  assert.doesNotMatch(page, /device\/|printed page/i);
});
