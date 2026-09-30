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

/** "Tuesday 9 September" for the archive register, where the month heading carries the year. */
export function formatDayInMonth(isoDate: string, language: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year!, month! - 1, day!));
  return new Intl.DateTimeFormat(locale(language), {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(date);
}

/** "September 2026" as the archive register's running head. */
export function formatMonth(isoDate: string, language: string): string {
  const [year, month] = isoDate.split("-").map(Number);
  const date = new Date(Date.UTC(year!, month! - 1, 1));
  return new Intl.DateTimeFormat(locale(language), {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** "05:00, Tuesday 9 September" for a cutoff timestamp, shown in the edition's timezone. */
export function formatCutoff(
  iso: string,
  language: string,
  timezone: string,
): string {
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
export function formatPublished(
  iso: string,
  language: string,
  timezone: string,
): string {
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

/**
 * The masthead ear: "Monday edition" and "News through 8am, 28 September", both read off the cutoff
 * in the edition's timezone so every archived edition says the same kind of thing. English shows
 * the hour as "8am" or "8.30am"; other languages keep the 24-hour clock.
 */
export function formatEar(
  iso: string,
  language: string,
  timezone: string,
): { label: string; through: string } {
  const date = new Date(iso);
  const weekday = new Intl.DateTimeFormat(locale(language), {
    weekday: "long",
    timeZone: timezone,
  }).format(date);
  const day = new Intl.DateTimeFormat(locale(language), {
    day: "numeric",
    month: "long",
    timeZone: timezone,
  }).format(date);
  let time: string;
  if (language === "en") {
    const parts = new Intl.DateTimeFormat("en-GB", {
      hour: "numeric",
      minute: "2-digit",
      hourCycle: "h12",
      timeZone: timezone,
    }).formatToParts(date);
    const hour = parts.find((p) => p.type === "hour")?.value ?? "";
    const minute = parts.find((p) => p.type === "minute")?.value ?? "00";
    const period = (parts.find((p) => p.type === "dayPeriod")?.value ?? "")
      .toLowerCase()
      .replace(/\./g, "");
    time = minute === "00" ? `${hour}${period}` : `${hour}.${minute}${period}`;
  } else {
    time = new Intl.DateTimeFormat(locale(language), {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone: timezone,
    }).format(date);
  }
  const label = language === "da" ? `${weekday}sudgave` : `${weekday} edition`;
  const through =
    language === "da"
      ? `Nyheder til ${time}, ${day}`
      : `News through ${time}, ${day}`;
  return { label: label.charAt(0).toUpperCase() + label.slice(1), through };
}
