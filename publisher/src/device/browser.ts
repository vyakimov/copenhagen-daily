// Section 9 and 11, kept small: one loopback server, one pinned Chromium, route blocking, font
// assertion, a single-evaluate overflow probe, and a viewport screenshot verified from its IHDR.
import { createServer, type Server } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import type { Browser, BrowserContext, Page } from "playwright";
import { hashBytes, hashFile } from "../publish/hash.ts";
import { publisherError } from "../publish/errors.ts";
import { STYLESHEET_URL } from "./render.ts";
import { pngHeader } from "./quantize.ts";

// The browser is installed hermetically under node_modules (OPERATIONS.md); tell Playwright so
// before it is imported, unless the operator pointed elsewhere on purpose.
process.env.PLAYWRIGHT_BROWSERS_PATH ??= "0";

export const FRAME = { width: 1872, height: 1404 } as const;
const REQUIRED_FACES = [
  ["Newsreader", "normal"],
  ["Newsreader", "italic"],
  ["Libre Franklin", "normal"],
  ["Libre Franklin", "italic"],
] as const;

export type SlotMeasurement = {
  available_px: number;
  content_px: number;
  natural_px: number;
  clipped: boolean;
  fits: boolean;
};
export type Measurement = {
  slots: Record<string, SlotMeasurement>;
  page_clipped: boolean;
  fits: boolean;
};

type Probe = {
  slots: Record<
    string,
    { available: number; content: number; natural: number; clipped: boolean }
  >;
  page_clipped: boolean;
  fonts: Array<{ family: string; style: string; status: string }>;
};

const probeInPage = (): Probe => {
  const slots: Probe["slots"] = {};
  for (const el of Array.from(
    document.querySelectorAll<HTMLElement>("[data-slot]"),
  )) {
    slots[el.dataset.slot!] = {
      available: el.clientHeight,
      content: el.scrollHeight,
      natural:
        el.querySelector<HTMLElement>(".story")?.offsetHeight ??
        el.scrollHeight,
      clipped:
        el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth,
    };
  }
  const page = document.querySelector(".device-page")!;
  return {
    slots,
    page_clipped:
      page.scrollHeight > page.clientHeight ||
      page.scrollWidth > page.clientWidth,
    fonts: Array.from(document.fonts).map((f) => ({
      family: f.family.replaceAll('"', ""),
      style: f.style,
      status: f.status,
    })),
  };
};

const settleInPage = async (): Promise<void> => {
  await Promise.all(Array.from(document.fonts).map((f) => f.load()));
  await document.fonts.ready;
  await new Promise<void>((done) =>
    requestAnimationFrame(() => requestAnimationFrame(() => done())),
  );
};

export class DeviceBrowser {
  readonly offOrigin: Array<{ category: string; url_sha256: string }> = [];
  readonly stylesheetSha256: string;
  readonly environment: {
    chromium: string;
    chromium_executable_sha256: string;
  };
  private readonly documents: Map<string, string>;
  private readonly server: Server;
  private readonly origin: string;
  private readonly browser: Browser;
  private readonly context: BrowserContext;
  private readonly page: Page;

  private constructor(parts: {
    documents: Map<string, string>;
    server: Server;
    origin: string;
    browser: Browser;
    context: BrowserContext;
    page: Page;
    environment: { chromium: string; chromium_executable_sha256: string };
    stylesheetSha256: string;
  }) {
    this.documents = parts.documents;
    this.server = parts.server;
    this.origin = parts.origin;
    this.browser = parts.browser;
    this.context = parts.context;
    this.page = parts.page;
    this.environment = parts.environment;
    this.stylesheetSha256 = parts.stylesheetSha256;
  }

  static async open(projectRoot: string): Promise<DeviceBrowser> {
    const css = (name: string) =>
      readFile(resolve(projectRoot, "assets/css", name), "utf8");
    const stylesheet = Buffer.from(
      `${await css("tokens.css")}\n${await css("device.css")}`,
    );
    const fontDir = resolve(projectRoot, "assets/fonts");
    const assets = new Map<string, { body: Buffer; type: string }>();
    assets.set(STYLESHEET_URL, {
      body: stylesheet,
      type: "text/css; charset=utf-8",
    });
    // The fonts sit beside the stylesheet, as they do in the release, so tokens.css's relative URLs resolve.
    const assetDir = STYLESHEET_URL.slice(0, STYLESHEET_URL.lastIndexOf("/"));
    for (const name of await readdir(fontDir)) {
      if (!name.endsWith(".woff2")) continue;
      assets.set(`${assetDir}/fonts/${name}`, {
        body: await readFile(resolve(fontDir, name)),
        type: "font/woff2",
      });
    }
    const documents = new Map<string, string>();
    const server = createServer((req, res) => {
      const path = req.url ?? "";
      const asset = assets.get(path);
      const doc = documents.get(path);
      if (asset) {
        res.writeHead(200, {
          "content-type": asset.type,
          "cache-control": "public, max-age=31536000, immutable",
        });
        res.end(asset.body);
      } else if (doc !== undefined) {
        res.writeHead(200, {
          "content-type": "text/html; charset=utf-8",
          "cache-control": "no-store",
        });
        res.end(doc);
      } else {
        res.writeHead(404);
        res.end();
      }
    });
    await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
    const address = server.address();
    if (!address || typeof address === "string")
      throw publisherError("renderer_unavailable", "loopback server failed");
    const origin = `http://127.0.0.1:${address.port}`;

    let playwright: typeof import("playwright");
    try {
      playwright = await import("playwright");
    } catch (error) {
      server.close();
      throw publisherError(
        "dependency_missing",
        "playwright is not installed",
        { cause: (error as Error).message },
      );
    }
    const executable = playwright.chromium.executablePath();
    let browser: Browser;
    try {
      browser = await playwright.chromium.launch({
        executablePath: executable,
        args: [
          "--force-color-profile=srgb",
          "--font-render-hinting=none",
          "--disable-lcd-text",
          "--hide-scrollbars",
        ],
      });
    } catch (error) {
      server.close();
      throw publisherError(
        "renderer_unavailable",
        "pinned Chromium could not be launched; see OPERATIONS.md",
        {
          component: "chromium",
          cause: (error as Error).message.split("\n")[0],
        },
      );
    }
    const context = await browser.newContext({
      viewport: { ...FRAME },
      deviceScaleFactor: 1,
      colorScheme: "light",
      forcedColors: "none",
      reducedMotion: "reduce",
      locale: "da-DK",
      timezoneId: "Europe/Copenhagen",
      serviceWorkers: "block",
    });
    const instance = new DeviceBrowser({
      documents,
      server,
      origin,
      browser,
      context,
      page: await context.newPage(),
      environment: {
        chromium: browser.version(),
        chromium_executable_sha256: await hashFile(executable),
      },
      stylesheetSha256: hashBytes(stylesheet),
    });
    await context.route("**/*", (route) => {
      const url = route.request().url();
      if (url.startsWith(`${origin}/`)) return route.continue();
      instance.offOrigin.push({
        category: route.request().resourceType(),
        url_sha256: hashBytes(url),
      });
      return route.abort("blockedbyclient");
    });
    return instance;
  }

  /** Serve the document at a content-addressed URL, settle fonts and layout, and read every slot once. */
  async measure(html: string): Promise<Measurement> {
    const path = `/c/${hashBytes(html).slice(7, 39)}/page.html`;
    this.documents.set(path, html);
    try {
      await this.page.goto(`${this.origin}${path}`, {
        waitUntil: "load",
        timeout: 30_000,
      });
      await this.page.evaluate(settleInPage);
    } catch (error) {
      throw publisherError(
        "render_timeout",
        "the device page did not load and settle",
        {
          cause: (error as Error).message.split("\n")[0],
        },
      );
    }
    const probe = await this.page.evaluate(probeInPage);
    if (this.offOrigin.length > 0) {
      throw publisherError(
        "network_access_blocked",
        "the device page attempted an off-origin request",
        {
          requests: this.offOrigin,
        },
      );
    }
    const missing = REQUIRED_FACES.filter(
      ([family, style]) =>
        !probe.fonts.some(
          (f) =>
            f.family === family && f.style === style && f.status === "loaded",
        ),
    );
    if (missing.length > 0) {
      throw publisherError("font_not_loaded", "a vendored face did not load", {
        missing: missing.map(([family, style]) => ({ family, style })),
        fonts: probe.fonts,
      });
    }
    const slots: Record<string, SlotMeasurement> = {};
    for (const [id, s] of Object.entries(probe.slots)) {
      if (![s.available, s.content, s.natural].every(Number.isFinite)) {
        throw publisherError(
          "measurement_inconsistent",
          "non-finite slot geometry",
          { slot: id },
        );
      }
      slots[id] = {
        available_px: s.available,
        content_px: s.content,
        natural_px: s.natural,
        clipped: s.clipped,
        fits: !s.clipped,
      };
    }
    const fits =
      !probe.page_clipped && Object.values(slots).every((s) => s.fits);
    return { slots, page_clipped: probe.page_clipped, fits };
  }

  /** Re-measure the frozen page and take a plain viewport screenshot; the frame is asserted from the IHDR. */
  async capture(html: string, expected: Measurement): Promise<Buffer> {
    const again = await this.measure(html);
    if (JSON.stringify(again) !== JSON.stringify(expected)) {
      throw publisherError(
        "measurement_inconsistent",
        "the frozen page measured differently at capture",
        {
          expected,
          measured: again,
        },
      );
    }
    if (!again.fits)
      throw publisherError(
        "measurement_inconsistent",
        "the frozen page does not fit at capture",
        {},
      );
    const png = await this.page.screenshot({
      type: "png",
      animations: "disabled",
      caret: "hide",
      scale: "css",
    });
    const header = pngHeader(png);
    if (header.width !== FRAME.width || header.height !== FRAME.height) {
      throw publisherError(
        "screenshot_size_mismatch",
        "the screenshot is not the device frame",
        {
          ...header,
          ...FRAME,
        },
      );
    }
    return png;
  }

  async close(): Promise<void> {
    await this.context.close().catch(() => {});
    await this.browser.close().catch(() => {});
    await new Promise<void>((done) => this.server.close(() => done()));
  }
}
