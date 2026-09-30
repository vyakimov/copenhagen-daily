import type { OptionSpec } from "./options.ts";

export type ParsedArgs = {
  action: string;
  options: Map<string, string | true>;
  positionals: string[];
};

function usage(message: string, details: Record<string, unknown>): Error {
  return Object.assign(new Error(message), { type: "usage_error", details });
}

/**
 * Parse `<action> [--option value] [--flag]`. With a spec for the action, every option must be one it
 * declares: a value option must get a value, a flag must not, none may repeat, and nothing may be
 * left over as a positional. Without a spec (an unknown action) the parse is lenient and the
 * dispatcher refuses the action itself.
 */
export function parseArgs(
  argv: string[],
  specs?: Record<string, OptionSpec>,
): ParsedArgs {
  const [action = "", ...rest] = argv;
  const spec = specs?.[action];
  const options = new Map<string, string | true>();
  const positionals: string[] = [];
  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i]!;
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const key = arg.slice(2);
    if (spec && !(key in spec)) {
      throw usage(`--${key} is not an option of ${action}`, {
        option: key,
        allowed: Object.keys(spec).sort(),
      });
    }
    if (options.has(key))
      throw usage(`--${key} was given more than once`, { option: key });
    const next = rest[i + 1];
    const takesValue = spec
      ? spec[key] === "value"
      : next !== undefined && !next.startsWith("--");
    if (takesValue) {
      if (next === undefined || next.startsWith("--"))
        throw usage(`--${key} needs a value`, { option: key });
      options.set(key, next);
      i += 1;
    } else options.set(key, true);
  }
  if (spec && positionals.length > 0) {
    throw usage(`${action} takes no positional arguments`, {
      unexpected: positionals,
    });
  }
  return { action, options, positionals };
}

export function requiredOption(args: ParsedArgs, name: string): string {
  const value = args.options.get(name);
  if (typeof value !== "string")
    throw usage(`--${name} is required`, { option: name });
  return value;
}
