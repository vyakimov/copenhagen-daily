import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";
import { resolve } from "node:path";
import { statSync } from "node:fs";

const input = process.env.PUBLISHER_BUILD_INPUT;
if (!input || !statSync(input).isDirectory()) throw new Error("PUBLISHER_BUILD_INPUT must name a directory");

// The CLI validated the edition against the contract already; this collection only carries it.
export const collections = {
  editions: defineCollection({
    loader: glob({ pattern: "*.json", base: resolve(input, "editions") }),
    schema: z.any(),
  }),
};
