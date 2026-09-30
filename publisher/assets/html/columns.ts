// Build-time column assignment for the grid composition's flow. CSS multicol balanced the flow at
// render time, so opening a story's source list re-balanced the whole section and Safari's first
// paint often left two columns empty. Stories are now dealt into fixed stacks here: contract order
// is kept, each stack is a contiguous run, and the cut points come from an estimate of each
// story's height in lines. Opening sources then pushes down only the stories beneath it.

export type Item<T> = {
  key: string;
  lines: number;
  leads?: boolean;
  value?: T;
};

const lines = (text: string | null | undefined, perLine: number): number =>
  text ? Math.ceil(text.length / perLine) : 0;

// Pixels per line and characters per line for each element at the grid composition's type scale in a
// column about 370px wide. Calibrated against rendered editions; only the ratios matter to the split.
const SCALE = {
  secondary: { headChars: 30, headLine: 29, deckChars: 40, deckLine: 29 },
  brief: { headChars: 40, headLine: 23, deckChars: 44, deckLine: 23 },
};
const BODY = { chars: 54, line: 25.6, paragraph: 10 };
const LEDE = { chars: 52, line: 22 };
const KICKER = 20;
const CALLOUT = 125;
const ATTRIBUTION = 45;
const PADDING = 16;

/** A rough rendered height in pixels: kicker, headline, deck, lede, paragraphs, callouts, source row. */
export function estimateHeight(story: any): number {
  const copy = story.copy ?? {};
  const scale = story.role === "brief" ? SCALE.brief : SCALE.secondary;
  const body: { text: string }[] =
    copy.body?.extended ?? copy.body?.standard ?? copy.body?.short ?? [];
  let total = KICKER + PADDING;
  total += lines(copy.headline, scale.headChars) * scale.headLine + 6;
  if (copy.deck)
    total += lines(copy.deck, scale.deckChars) * scale.deckLine + 6;
  if (copy.lede && story.role === "brief")
    total += lines(copy.lede.text, LEDE.chars) * LEDE.line;
  for (const p of body)
    total += lines(p.text, BODY.chars) * BODY.line + BODY.paragraph;
  total += (story.callouts?.length ?? 0) * CALLOUT;
  total += story.sources?.length ? ATTRIBUTION : 8;
  return total;
}

/**
 * Deal items into `count` contiguous stacks. An item marked `leads` (a heading) is welded to the item
 * after it, so the two are placed as one unit and a heading can never end a column. Filling left to
 * right, a column takes the next unit only if that leaves the tallest column shorter than stopping
 * would, judging the columns still to come by their fair share of what remains.
 */
export function splitColumns<T>(items: Item<T>[], count: number): Item<T>[][] {
  const units: Item<T>[][] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!;
    if (item.leads && i + 1 < items.length) {
      units.push([item, items[i + 1]!]);
      i++;
    } else {
      units.push([item]);
    }
  }
  const height = (unit: Item<T>[]) =>
    unit.reduce((sum, item) => sum + item.lines, 0);
  const columns: Item<T>[][] = Array.from({ length: count }, () => []);
  let index = 0;
  let remaining = units.reduce((sum, unit) => sum + height(unit), 0);
  for (let c = 0; c < count; c++) {
    const later = count - c - 1;
    let filled = 0;
    while (index < units.length) {
      const unit = units[index]!;
      const leftAfter = units.length - index - 1;
      // Every later column must still get a unit, unless there are fewer units than columns.
      if (later > 0 && filled > 0) {
        if (leftAfter < later) break;
        const ifTaken = Math.max(
          filled + height(unit),
          (remaining - height(unit)) / later,
        );
        const ifStopped = Math.max(filled, remaining / later);
        if (ifTaken >= ifStopped) break;
      }
      columns[c]!.push(...unit);
      filled += height(unit);
      remaining -= height(unit);
      index++;
    }
  }
  return columns;
}
