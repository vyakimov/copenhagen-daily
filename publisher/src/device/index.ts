// The device path as one call: fit, capture, quantize, verify. Throws a publisher error with the fit
// report in its details on any failure; the store decides what a failure means for publication.
import type { EditionContract } from "../contract/edition-contract.ts";
import { hashBytes } from "../publish/hash.ts";
import { DeviceBrowser, FRAME } from "./browser.ts";
import { fitEdition, type FitReport, type TitleLike } from "./fit.ts";
import type { DevicePlan } from "./render.ts";
import { toFourBitGrey, verifyDevicePng } from "./quantize.ts";

export type DeviceEnvironment = { chromium: string; chromium_executable_sha256: string };
export type DeviceOutput = {
  plan: DevicePlan;
  report: FitReport;
  html: string;
  master: Buffer;
  png: Buffer;
  image_sha256: string;
  stylesheet_sha256: string;
  environment: DeviceEnvironment;
};

/** Classes of device failure that must stop publication rather than degrade to a web-only edition. */
export const DEVICE_INTEGRITY_ERRORS = new Set([
  "measurement_inconsistent",
  "screenshot_size_mismatch",
  "image_invariant_violation",
  "network_access_blocked",
]);

export async function withBrowser<T>(projectRoot: string, body: (browser: DeviceBrowser) => Promise<T>): Promise<T> {
  const browser = await DeviceBrowser.open(projectRoot);
  try {
    return await body(browser);
  } finally {
    await browser.close();
  }
}

export async function buildDevice(
  projectRoot: string,
  edition: EditionContract,
  config: TitleLike,
  options: { capture?: boolean } = {},
): Promise<DeviceOutput> {
  return withBrowser(projectRoot, async (browser) => {
    const fit = await fitEdition(browser, edition, config);
    const master = options.capture === false ? Buffer.alloc(0) : await browser.capture(fit.html, fit.measurement);
    const png = master.length ? toFourBitGrey(master) : master;
    if (png.length) verifyDevicePng(png, FRAME.width, FRAME.height);
    return {
      plan: fit.plan,
      report: fit.report,
      html: fit.html,
      master,
      png,
      image_sha256: hashBytes(png),
      stylesheet_sha256: browser.stylesheetSha256,
      environment: browser.environment,
    };
  });
}
