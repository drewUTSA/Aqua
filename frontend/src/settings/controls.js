const field = (scope, key, label, help = "") => ({ scope, key, label, help });
export const CATEGORIES = [
  { id: "appearance", title: "Appearance", description: "Preview a clear, comfortable interface.", fields: [
    field("account", "theme", "Theme", "Follow system uses this device’s light or dark preference."),
    field("account", "accent", "Accent"), field("device", "contrast", "Contrast"), field("device", "text_scale", "Text size", "Browser zoom remains available."),
    field("device", "line_spacing", "Reading line spacing"), field("account", "density", "Interface density"),
    field("account", "specks", "Background specks", "Specks are static and stay clear of reading surfaces."),
    field("account", "surface", "Surface treatment"), field("account", "font", "Typeface") ] },
  { id: "workspace", title: "Workspace", description: "Keep navigation and reading space useful on this device.", fields: [
    field("device", "sidebar", "Sidebar"), field("account", "sidebar_sections", "Sidebar sections", "Show, hide and reorder optional sections. New Chat and account access remain available."),
    field("account", "recents_count", "Recents shown", "See all remains available."), field("device", "conversation_width", "Conversation width"),
    field("device", "split_percent", "Conversation share when visuals are open", "25–65%. The responsive layout keeps both panes usable; New Chat starts with visuals closed.") ] },
  { id: "chat", title: "Chat & AI", description: "Presentation changes apply without rerunning a question.", fields: [
    field("device", "send_shortcut", "Send shortcut", "A visible Send button always remains. Shift+Enter inserts a new line."),
    field("account", "suggestions", "Starter suggestions", "Show suggested questions on New Chat; this does not generate follow-ups."), field("account", "timestamps", "Timestamps", "Ordering, errors and freshness information remain visible."),
    field("device", "auto_scroll", "Auto-scroll", "Follow new output only while you are near the bottom."),
    field("account", "wrap_code", "Wrap long code lines", "Copied SQL remains unchanged.") ] },
  { id: "charts", title: "Charts & tables", description: "Keep charts linked to their source data and conversation.", fields: [
    field("account", "initial_result_view", "Initial result view", "An explicit request for a chart or table takes precedence."),
    field("account", "palette", "Series palette", "Used where appropriate for the chart; text and table alternatives always remain."),
    field("account", "legend", "Labels and legends", "Essential units and distinctions remain available."),
    field("account", "grid", "Grid lines"), field("device", "chart_motion", "Chart transitions"),
    field("account", "preserve_exploration", "Preserve exploration", "Keep compatible zoom; reset when axis meaning or units change."),
    field("account", "table_density", "Table density"), field("account", "table_page_size", "Table rows per page", "This changes display pages, never the server’s row or export limits."),
    field("account", "precision", "Number precision", "Full source precision remains available on demand. Currency is never converted.") ] },
  { id: "accessibility", title: "Accessibility", description: "Keyboard focus, basic chart alternatives and usable touch targets are always on.", fields: [
    field("device", "motion", "Motion", "Reduce motion overrides decorative transitions."), field("device", "contrast", "Contrast"),
    field("device", "text_scale", "Text size"), field("device", "line_spacing", "Reading line spacing"),
    field("device", "announcements", "Announcements", "Reduced announcements retain essential status and error feedback."),
    field("account", "expanded_summaries", "Expanded chart summaries", "Basic text alternatives are always available.") ] },
  { id: "notifications", title: "Notifications", description: "Essential errors and account security notices remain visible.", fields: [] },
  { id: "region", title: "Language & region", description: "Format source values without changing their meaning.", fields: [
    field("account", "locale", "Dates and numbers", "The interface is available in English. These options change regional formatting only."),
    field("account", "timezone", "Timezone", "Detect device uses the named timezone shown in the sample."),
    field("account", "date_style", "Date style"), field("account", "time_format", "Time format") ] },
  { id: "account", title: "Account & security", description: "Sign-in and data permissions are managed separately from preferences.", fields: [] },
  { id: "privacy", title: "Privacy & data", description: "Move safe presentation preferences between devices.", fields: [] }
];
export const VALUE_LABELS = {
  opal: "Opal dark", light: "Light", system: "Follow device preference", pearl: "Pearl", sage: "Sage", slate: "Slate", amber: "Amber",
  standard: "Standard", increased: "Increased", comfortable: "Comfortable", compact: "Compact", subtle: "Subtle", off: "Off", solid: "Solid", depth: "Soft depth",
  manrope: "Manrope", expanded: "Expanded", collapsed: "Collapsed", focused: "Focused", wide: "Wide", relaxed: "Relaxed",
  enter: "Enter to send", modified_enter: "Ctrl/Cmd+Enter to send", always: "Always show", hidden: "Hide nonessential timestamps",
  follow: "Follow while near bottom", manual: "Manual", chart: "Chart", table: "Table", categorical: "Accessible categorical",
  sequential: "Sequential", diverging: "Diverging", auto: "Automatic", show: "Show", hide: "Hide", minimal: "Minimal", reduce: "Reduce motion",
  reduced: "Reduced", "en-US": "English · United States formats", "en-GB": "English · United Kingdom formats", device: "Detect device",
  medium: "Medium", short: "Short", long: "Long", locale: "Locale default", "12": "12-hour", "24": "24-hour"
};
export const valueLabel = (key, value) => key === "text_scale" ? `${value}%` : key === "precision" && value !== "auto" ? `${value} decimal places`
  : key === "font" && value === "system" ? "System sans" : key === "theme" && value === "system" ? "Follow system"
    : VALUE_LABELS[value] || String(value);
export function sectionDefaults(category, accountDefaults, deviceDefaults) {
  const result = { account: {}, device: {} };
  for (const { scope, key } of category.fields) result[scope][key] = (scope === "account" ? accountDefaults : deviceDefaults)[key];
  return result;
}
