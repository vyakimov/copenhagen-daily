// Device path invariants (Section 1, 5 and 11): the frame, the 4-bit grey PNG, determinism, no
// scripts, the fit failure that names its slot, and the web-only fallback that keeps the previous
// device page. These run the pinned Chromium and ImageMagick; they are the slow tests.
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import {
  readEdition,
  validateEdition,
} from "../src/contract/edition-contract.ts";
import { loadTitleConfig } from "../src/contract/title-config.ts";
import { buildDevice, withBrowser } from "../src/device/index.ts";
import { fitEdition } from "../src/device/fit.ts";
import { renderDevicePage } from "../src/device/render.ts";
import {
  MAGICK_ARGS,
  pngHeader,
  toFourBitGrey,
  verifyDevicePng,
} from "../src/device/quantize.ts";
import { publishEdition } from "../src/publish/store.ts";
import { hashBytes, hashFile } from "../src/publish/hash.ts";

const projectRoot = resolve(import.meta.dirname, "..");
const config = loadTitleConfig(resolve(projectRoot, "config/title.yaml"));

async function edition(name: string) {
  const checked = validateEdition(
    await readEdition(resolve(projectRoot, "contracts/examples", name)),
  );
  assert.equal(checked.valid, true);
  if (!checked.valid) throw new Error("unreachable");
  return checked.value;
}

test("the dense edition renders one 1872 x 1404 4-bit grey PNG, deterministically, without scripts", async () => {
  const doc = await edition("dense.json");
  const first = await buildDevice(projectRoot, doc, config);
  const second = await buildDevice(projectRoot, doc, config);
  assert.doesNotMatch(first.html, /<script/i);
  const header = verifyDevicePng(first.png, 1872, 1404);
  assert.equal(header.bit_depth, 4);
  assert.equal(header.color_type, 0);
  assert.deepEqual([...new Set(header.chunks)].sort(), [
    "IDAT",
    "IEND",
    "IHDR",
  ]);
  assert.ok(header.levels <= 16);
  assert.equal(pngHeader(first.master).width, 1872);
  // Two captures of one plan and two conversions of one master are byte-identical.
  assert.equal(hashBytes(first.master), hashBytes(second.master));
  assert.equal(hashBytes(toFourBitGrey(first.master)), hashBytes(first.png));
  assert.equal(first.image_sha256, second.image_sha256);
  // The lead is always placed and reading order preserves contract order.
  assert.equal(first.plan.placements[0]!.slot, "lead");
  const order = doc.stories.map((s) => s.id);
  const placed = first.plan.placements.map((p) => p.story_id);
  assert.deepEqual(
    placed,
    order.filter((id) => placed.includes(id)),
  );
  assert.equal(first.report.status, "fit");
  assert.equal(first.report.off_origin_requests.length, 0);
});

test("lead-only and lead-plus-one-brief fit without repairs", async () => {
  await withBrowser(projectRoot, async (browser) => {
    for (const name of ["minimal.json", "sparse.json"]) {
      const result = await fitEdition(browser, await edition(name), config);
      assert.equal(result.report.repairs.length, 0, name);
      assert.equal(result.measurement.fits, true, name);
    }
  });
});

test("a required story that cannot fit fails naming its slot and the overflow", async () => {
  await assert.rejects(
    buildDevice(projectRoot, await edition("required-overflow.json"), config),
    (error: any) => {
      assert.equal(error.type, "fit_failed_required_story");
      assert.equal(typeof error.details.slot, "string");
      assert.ok(error.details.overflow_px > 0);
      assert.equal(error.details.fit_report.status, "failed");
      assert.ok(error.details.fit_report.attempts.length > 0);
      return true;
    },
  );
});

test("the conversion command is the verified no-dither reduction", () => {
  assert.deepEqual(
    [...MAGICK_ARGS],
    [
      "png:-",
      "-strip",
      "-colorspace",
      "Gray",
      "-depth",
      "4",
      "-define",
      "png:color-type=0",
      "-define",
      "png:bit-depth=4",
      "png:-",
    ],
  );
});

test("a device failure publishes web-only as partial and keeps the previous device page", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-device-"));
  try {
    const common = {
      root,
      projectRoot,
      dryRun: false,
      skipDevice: false,
      requireDevice: false,
    };
    const first = await publishEdition({
      ...common,
      edition: await edition("sparse.json"),
    });
    assert.equal(first.status, "published");
    assert.equal(first.device_status, "published");
    const current = join(root, "live", "device", "current.png");
    const before = {
      hash: await hashFile(current),
      mtime: (await stat(current)).mtimeMs,
    };
    const bundle = join(root, "store", "n", "2026-09-09-sparse");
    assert.equal(
      await hashFile(join(bundle, "device", "page-1.png")),
      before.hash,
    );
    const receipt = JSON.parse(
      await readFile(join(bundle, "publication-receipt.json"), "utf8"),
    );
    assert.equal(receipt.device.status, "published");
    assert.ok(receipt.web.story_ids.length >= receipt.device.story_ids.length);

    const overflow = await edition("required-overflow.json");
    await assert.rejects(
      publishEdition({ ...common, requireDevice: true, edition: overflow }),
      (e: any) => {
        assert.equal(e.type, "fit_failed_required_story");
        return true;
      },
    );
    const second = await publishEdition({ ...common, edition: overflow });
    assert.equal(second.status, "partial");
    assert.equal(second.device_status, "failed");
    assert.equal(await hashFile(current), before.hash);
    assert.equal((await stat(current)).mtimeMs, before.mtime);
    const latest = JSON.parse(
      await readFile(join(root, "live", "latest.json"), "utf8"),
    );
    assert.equal(latest.device.edition_id, "2026-09-09-sparse");
    assert.equal(latest.web.edition_id, overflow.edition.id);
    const failed = join(root, "store", "n", overflow.edition.id);
    await assert.rejects(stat(join(failed, "device")));
    await assert.rejects(stat(join(failed, "composition.json")));
    const page = await readFile(join(failed, "index.html"), "utf8");
    assert.doesNotMatch(page, /device\/page-1\.png/);
  } finally {
    // Store directories are frozen to 0555; make them writable before removing the temporary root.
    spawnSync("chmod", ["-R", "u+w", root]);
    await rm(root, { recursive: true, force: true });
  }
});

test("count repair omits an optional brief instead of demoting a secondary into a full brief band", async () => {
  const base = await edition("minimal.json");
  const lead = base.stories[0]!;
  const short = (
    id: string,
    role: "secondary" | "brief",
    extra: Record<string, unknown> = {},
  ) => ({
    ...lead,
    id,
    role,
    device_participation: "required",
    kicker: "Denmark",
    copy: {
      headline: `${id} headline`,
      lede: {
        text: `${id} lede.`,
        sources: lead.copy.body.standard![0]!.sources,
      },
      body: {
        standard: [
          {
            text: `${id} body text.`,
            sources: lead.copy.body.standard![0]!.sources,
          },
        ],
      },
    },
    callouts: [],
    ...extra,
  });
  const doc = validateEdition({
    ...base,
    stories: [
      lead,
      short("sec-1", "secondary", { fallback_role: "brief" }),
      short("brief-1", "brief"),
      short("brief-2", "brief"),
      short("brief-3", "brief"),
      short("brief-4", "brief"),
      short("brief-5", "brief", { device_participation: "optional" }),
    ],
    fit_policy: {
      ...base.fit_policy,
      allow_role_fallback: true,
      omittable_story_ids: ["brief-5"],
    },
  });
  assert.ok(doc.valid, JSON.stringify((doc as any).issues));
  await withBrowser(projectRoot, async (browser) => {
    const result = await fitEdition(browser, doc.value, config);
    assert.equal(result.report.status, "fit");
    assert.deepEqual(
      result.plan.omitted.map((o) => o.story_id),
      ["brief-5"],
    );
    const secondary = result.plan.placements.find(
      (p) => p.story_id === "sec-1",
    );
    assert.equal(
      secondary?.role_as_placed,
      "secondary",
      "the secondary must keep its band",
    );
  });
});

test("the saved device page links the versioned stylesheet that the release actually carries", async () => {
  const root = await mkdtemp(join(tmpdir(), "publish-device-css-"));
  const result = await publishEdition({
    root,
    projectRoot,
    dryRun: false,
    skipDevice: false,
    requireDevice: true,
    edition: await edition("sparse.json"),
  });
  assert.equal(result.device_status, "published");
  const html = await readFile(
    join(root, "live", "n", "2026-09-09-sparse", "device", "page-1.html"),
    "utf8",
  );
  const match = html.match(/<link rel="stylesheet" href="([^"]+)"/);
  assert.ok(match, "device page links a stylesheet");
  const served = join(root, "live", match![1]!.replace(/^\//, ""));
  assert.ok(
    await stat(served).then((s) => s.isFile()),
    `${match![1]} is in the release`,
  );
});

test("the device page credits wire copy to its agency", async () => {
  const wire = await edition("wire.json");
  const story = wire.stories[0]!;
  const html = renderDevicePage(
    wire,
    {
      composition: "lead-wide",
      placements: [
        {
          story_id: story.id,
          role_as_placed: "lead",
          slot: "lead",
          headline_variant: "headline",
          copy_variant: null,
          callout_index: story.callouts.findIndex((c) => c.kind === "quote"),
        },
      ],
      omitted: [],
      dropped_callouts: [],
    },
    config,
  );
  assert.match(html, /<div class="src">Ritzau · DR · Berlingske · Jyllands-Posten · \+2<\/div>/);
  assert.match(html, /quoted by Ritzau/);
  assert.doesNotMatch(html, /Kristeligt Dagblad/);
});
