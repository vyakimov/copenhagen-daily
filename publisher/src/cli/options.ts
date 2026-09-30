// Every option each action accepts, and whether it takes a value. The parser refuses anything else
// before an action runs, so a misspelt flag can never be ignored on the way to a publish.
export type OptionKind = "value" | "flag";
export type OptionSpec = Record<string, OptionKind>;

export const OPTIONS: Record<string, OptionSpec> = {
  "list-actions": {},
  version: {},
  doctor: {},
  check: {},
  schema: { name: "value" },
  validate: { edition: "value" },
  "build-web": {
    edition: "value",
    output: "value",
    layout: "value",
    "dry-run": "flag",
  },
  preview: {
    edition: "value",
    "publish-root": "value",
    output: "value",
    layout: "value",
    port: "value",
  },
  fit: { edition: "value" },
  "render-device": { edition: "value", output: "value", "dry-run": "flag" },
  publish: {
    edition: "value",
    "publish-root": "value",
    "keep-releases": "value",
    "crash-at": "value",
    "skip-device": "flag",
    "require-device": "flag",
    "dry-run": "flag",
  },
  recover: { "publish-root": "value", "dry-run": "flag" },
  receipt: { "publish-root": "value", edition: "value" },
  verify: { "publish-root": "value", edition: "value" },
};
