export const ACTIONS = [
  ["build-web", "Build and verify a web edition"],
  ["check", "Run offline lint, type, test, and wrapper checks"],
  ["doctor", "Report pinned renderer dependencies"],
  ["fit", "Measure and fit a device composition"],
  ["list-actions", "List supported actions"],
  ["preview", "Build an edition into a local site and serve it"],
  ["publish", "Publish an immutable web and device bundle"],
  ["receipt", "Read an activated publication receipt"],
  ["recover", "Recover a pending publication activation"],
  ["render-device", "Render a frozen device composition"],
  ["schema", "Return a public contract schema"],
  ["validate", "Validate an edition contract"],
  ["verify", "Verify a published bundle"],
  ["version", "Report CLI and contract versions"],
] as const;

export const actionCatalog = () => ACTIONS.map(([name, description]) => ({ name, description }));
