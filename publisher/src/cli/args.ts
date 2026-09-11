export type ParsedArgs = { action: string; options: Map<string, string | true>; positionals: string[] };

export function parseArgs(argv: string[]): ParsedArgs {
  const [action = "", ...rest] = argv;
  const options = new Map<string, string | true>();
  const positionals: string[] = [];
  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i]!;
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const key = arg.slice(2);
    const next = rest[i + 1];
    if (next && !next.startsWith("--")) {
      options.set(key, next);
      i += 1;
    } else options.set(key, true);
  }
  return { action, options, positionals };
}

export function requiredOption(args: ParsedArgs, name: string): string {
  const value = args.options.get(name);
  if (typeof value !== "string")
    throw Object.assign(new Error(`--${name} is required`), { type: "usage_error", details: { option: name } });
  return value;
}
