// Who a source is credited to. Wire copy is the agency's reporting on a carrier's page: the reader sees
// the agency's name, and the link still opens the outlet that published it.
export type CreditNames = { publishers: Record<string, string>; agencies?: Record<string, string> };
type Credited = { source: string; wire?: string; primary?: boolean };

const publisherName = (id: string, names: CreditNames) => names.publishers[id] ?? id;

/** The agency for a wire article, else the publisher. */
export function sourceName(source: Credited, names: CreditNames): string {
  return source.wire ? (names.agencies?.[source.wire] ?? source.wire) : publisherName(source.source, names);
}

/** The full credit in the evidence list: a wire article names its agency and its carrier. */
export function sourceCredit(source: Credited, names: CreditNames): string {
  const name = sourceName(source, names);
  return source.wire ? `${name} via ${publisherName(source.source, names)}` : name;
}

/** One name per contributing party, the primary's first, then in contract order. */
export function storyCredits(sources: Credited[], names: CreditNames): string[] {
  const primary = sources.find((s) => s.primary);
  return [...new Set([...(primary ? [primary] : []), ...sources].map((s) => sourceName(s, names)))];
}

/**
 * Publisher ids to the name a quote's reporter is shown by. A quote names a publisher, not an article,
 * so it is the agency's only when every article the publisher contributed to the story is that agency's.
 */
export function quoteNames(sources: Credited[], names: CreditNames): Record<string, string> {
  const out = { ...names.publishers };
  for (const id of new Set(sources.map((s) => s.source))) {
    const credits = new Set(sources.filter((s) => s.source === id).map((s) => sourceName(s, names)));
    if (credits.size === 1) out[id] = [...credits][0]!;
  }
  return out;
}
