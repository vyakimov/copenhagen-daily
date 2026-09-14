// Section 11: the 4-bit grayscale conversion and the PNG assertions that gate device success.
import { spawnSync } from "node:child_process";
import { publisherError } from "../publish/errors.ts";

/** Round-to-nearest depth reduction, no dithering, no metadata. Assert this array, never edit it casually. */
export const MAGICK_ARGS = [
  "png:-", "-strip", "-colorspace", "Gray", "-depth", "4",
  "-define", "png:color-type=0", "-define", "png:bit-depth=4", "png:-",
] as const;

/** ImageMagick 7's binary; cron environments without /opt/homebrew/bin on PATH can point at it directly. */
const MAGICK = process.env.PUBLISHER_MAGICK ?? "magick";

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export type PngHeader = { width: number; height: number; bit_depth: number; color_type: number; chunks: string[] };

/** IHDR fields and the chunk-type list, read in plain Node. */
export function pngHeader(buffer: Buffer): PngHeader {
  if (buffer.length < 33 || !buffer.subarray(0, 8).equals(SIGNATURE) || buffer.toString("latin1", 12, 16) !== "IHDR") {
    throw publisherError("image_invariant_violation", "not a PNG", {});
  }
  const chunks: string[] = [];
  for (let offset = 8; offset + 8 <= buffer.length; ) {
    const length = buffer.readUInt32BE(offset);
    chunks.push(buffer.toString("latin1", offset + 4, offset + 8));
    offset += 12 + length;
  }
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
    bit_depth: buffer[24]!,
    color_type: buffer[25]!,
    chunks,
  };
}

export function toFourBitGrey(master: Buffer): Buffer {
  const result = spawnSync(MAGICK, [...MAGICK_ARGS], {
    input: master,
    maxBuffer: 64 * 1024 * 1024,
    env: { ...process.env, SOURCE_DATE_EPOCH: "0" },
  });
  if (result.error || result.status !== 0) {
    throw publisherError("quantize_failed", "ImageMagick conversion failed; is magick installed?", {
      cause: result.error?.message ?? result.stderr.toString("utf8").slice(-1000),
    });
  }
  return result.stdout;
}

/** The device invariant: 1872 x 1404, colour type 0, bit depth 4, only IHDR/IDAT/IEND, at most 16 levels. */
export function verifyDevicePng(png: Buffer, width: number, height: number): PngHeader & { levels: number } {
  const header = pngHeader(png);
  const chunkSet = [...new Set(header.chunks)].sort();
  const ok =
    header.width === width && header.height === height && header.bit_depth === 4 && header.color_type === 0 &&
    JSON.stringify(chunkSet) === JSON.stringify(["IDAT", "IEND", "IHDR"]);
  if (!ok) throw publisherError("image_invariant_violation", "device PNG does not meet the frame invariant", header);
  const identify = spawnSync(MAGICK, ["identify", "-format", "%k", "png:-"], { input: png, encoding: "utf8" });
  const levels = Number(identify.stdout.trim());
  if (identify.status !== 0 || !Number.isInteger(levels) || levels > 16) {
    throw publisherError("image_invariant_violation", "device PNG has more than 16 grey levels", { levels });
  }
  return { ...header, levels };
}
