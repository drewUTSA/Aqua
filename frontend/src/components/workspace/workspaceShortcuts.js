// Kept separate so keyboard handling does not eagerly load the switcher index.
export function workspaceShortcut(event, { hidden = false, modalOpen = false } = {}) {
  if (hidden || modalOpen || event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229 || event.altKey) return null;
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "k") return "switch";
  const editable = event.target?.closest?.("input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=textbox]");
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.shiftKey && !editable) return "composer";
  return null;
}
