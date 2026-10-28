const locales = new Set(["en-US", "en-GB"]);
const zones = new Set(["UTC", "America/Chicago", "America/New_York", "America/Los_Angeles", "Europe/London"]);

/** Display only: timestamps retain their source text and currencies retain units. */
export function dateOptions(preferences = {}, dateOnly = false) {
  const zone = zones.has(preferences.timezone) ? preferences.timezone : undefined;
  const dateStyle = ["short", "medium", "long"].includes(preferences.date_style) ? preferences.date_style : "medium";
  return { locale: locales.has(preferences.locale) ? preferences.locale : "en-US",
    options: { dateStyle, ...(dateOnly ? { timeZone: "UTC" } : { timeStyle: "short", ...(zone ? { timeZone: zone } : {}),
      ...(["12", "24"].includes(preferences.time_format) ? { hour12: preferences.time_format === "12" } : {}) }) } };
}

export function formatTimestamp(value, preferences) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  const { locale, options } = dateOptions(preferences);
  return new Intl.DateTimeFormat(locale, options).format(date);
}

export function numberOptions(preferences = {}, fallbackDigits = 2) {
  const digits = ["0", "2", "4", "6"].includes(preferences.precision) ? Number(preferences.precision) : fallbackDigits;
  return { locale: locales.has(preferences.locale) ? preferences.locale : "en-US", digits };
}
