import { CLI_VERSION, ENVELOPE_VERSION } from "./version.ts";

export type PublisherError = { type: string; message: string; details: Record<string, unknown> };

function sorted(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => [k, sorted(v)]),
    );
  }
  return value;
}

export function emit(action: string, result: unknown): void {
  process.stdout.write(
    JSON.stringify(
      sorted({ ok: true, action, result, meta: { cli_version: CLI_VERSION, envelope_version: ENVELOPE_VERSION } }),
    ) + "\n",
  );
}

export function emitError(action: string, error: PublisherError): void {
  process.stdout.write(
    JSON.stringify(
      sorted({ ok: false, action, error, meta: { cli_version: CLI_VERSION, envelope_version: ENVELOPE_VERSION } }),
    ) + "\n",
  );
}
