// Reader-facing date and time strings. Formatted once, in Node, from the contract's validated
// language and timezone. The manifest records the Node and ICU versions that produced them.

const LOCALES: Record<string, string> = { en: "en-GB", da: "da-DK" };

function locale(language: string): string {
  return LOCALES[language] ?? "en-GB";
}

/** "Tuesday 9 September 2026" for an edition date such as 2026-09-09. */
export function formatEditionDate(isoDate: string, language: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year!, month! - 1, day!));
  return new Intl.DateTimeFormat(locale(language), {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** "05:00, Tuesday 9 September" for a cutoff timestamp, shown in the edition's timezone. */
export function formatCutoff(iso: string, language: string, timezone: string): string {
  const date = new Date(iso);
  const time = new Intl.DateTimeFormat(locale(language), {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).format(date);
  const day = new Intl.DateTimeFormat(locale(language), {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: timezone,
  }).format(date);
  return `${time}, ${day}`;
}

/** "9 Sep 2026, 14:00" for an article's publication time, shown in the edition's timezone. */
export function formatPublished(iso: string, language: string, timezone: string): string {
  return new Intl.DateTimeFormat(locale(language), {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timezone,
  }).format(new Date(iso));
}
