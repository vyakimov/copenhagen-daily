import { defineConfig } from "astro/config";

// Every path is supplied by the CLI per run; a missing one is a build failure, never a default.
if (!process.env.PUBLISHER_ASTRO_OUT || !process.env.PUBLISHER_ASTRO_CACHE) {
  throw new Error("PUBLISHER_ASTRO_OUT and PUBLISHER_ASTRO_CACHE are required");
}

export default defineConfig({
  output: "static",
  outDir: process.env.PUBLISHER_ASTRO_OUT,
  cacheDir: process.env.PUBLISHER_ASTRO_CACHE,
  // v7 defaults to 'jsx', which strips whitespace between inline elements in source rows.
  compressHTML: false,
  build: { format: "directory", assets: "_astro", inlineStylesheets: "never" },
  trailingSlash: "always",
  devToolbar: { enabled: false },
});
