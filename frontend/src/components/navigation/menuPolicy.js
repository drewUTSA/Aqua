// Menu navigation is local presentation work: it cannot create model choices
// or turn display metadata into an operation or a network request.
export function moveMenuIndex(key, current, enabled) {
  if (!enabled.length) return -1;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled.at(-1);
  if (!["ArrowDown", "ArrowUp"].includes(key)) return current;
  const index = enabled.indexOf(current), direction = key === "ArrowDown" ? 1 : -1;
  if (index < 0) return key === "ArrowDown" ? enabled[0] : enabled.at(-1);
  return enabled[(index + direction + enabled.length) % enabled.length];
}

export function matchMenuText(labels, query, current) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return current;
  const text = [...normalized].every(character => character === normalized[0]) ? normalized[0] : normalized;
  for (let offset = 1; offset <= labels.length; offset++) {
    const index = (current + offset + labels.length) % labels.length;
    if (labels[index].toLocaleLowerCase().startsWith(text)) return index;
  }
  return current;
}

export function advertisedModels(value) {
  if (!Array.isArray(value) || value.length > 32) return [];
  const seen = new Set(), result = [];
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item)
      || typeof item.id !== "string" || !item.id.length || item.id.length > 128 || /[\u0000-\u001f\u007f]/u.test(item.id)
      || typeof item.name !== "string" || !item.name.trim() || item.name.length > 160 || seen.has(item.id)) return [];
    seen.add(item.id);
    result.push({ id: item.id, name: item.name,
      description: typeof item.description === "string" && item.description.length <= 500 ? item.description : "" });
  }
  return result;
}

export function placeMenu(anchor, measuredHeight, viewport, { width = 320, placement = "above", align = "start" } = {}) {
  const inset = 12, gap = 8, leftEdge = viewport.left || 0, topEdge = viewport.top || 0;
  const availableWidth = Math.max(1, viewport.width - inset * 2), safeWidth = Math.min(width, availableWidth);
  const bottomEdge = topEdge + viewport.height, above = Math.max(0, anchor.top - topEdge - inset - gap);
  const below = Math.max(0, bottomEdge - inset - anchor.bottom - gap);
  const preferAbove = placement !== "below";
  const side = preferAbove ? above >= Math.min(measuredHeight, 160) || above >= below : !(below >= Math.min(measuredHeight, 160) || below >= above);
  const maxHeight = Math.max(1, Math.min(viewport.height - inset * 2, side ? above : below));
  const height = Math.min(measuredHeight, maxHeight);
  const clamp = (value, min, max) => Math.min(Math.max(value, min), Math.max(min, max));
  return { width: safeWidth, maxHeight,
    left: clamp(align === "end" ? anchor.right - safeWidth : anchor.left, leftEdge + inset, leftEdge + viewport.width - inset - safeWidth),
    top: clamp(side ? anchor.top - gap - height : anchor.bottom + gap, topEdge + inset, bottomEdge - inset - height) };
}
