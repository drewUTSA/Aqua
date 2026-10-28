import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { placeMenu } from "./menuPolicy.js";

// A manual popover stays in the DOM's account/dialog scope while entering the
// top layer. It avoids both overflow clipping and a portal outside a modal.
export function useMenuSurface(open, trigger, panel, { width, placement = "above", align = "start", dismiss }) {
  const [position, setPosition] = useState(null);
  const dismissRef = useRef(dismiss); dismissRef.current = dismiss;
  const locate = useCallback(() => {
    if (!trigger.current || !panel.current) return;
    const rect = trigger.current.getBoundingClientRect();
    if (!trigger.current.isConnected || !rect.width || !rect.height || trigger.current.closest("[hidden],[inert]")
      || ["hidden", "collapse"].includes(getComputedStyle(trigger.current).visibility)) {
      if (panel.current.hidePopover && panel.current.matches(":popover-open")) panel.current.hidePopover();
      dismissRef.current?.(); return;
    }
    const viewport = window.visualViewport;
    setPosition(placeMenu(rect, panel.current.getBoundingClientRect().height,
      { width: viewport?.width || innerWidth, height: viewport?.height || innerHeight,
        left: viewport?.offsetLeft || 0, top: viewport?.offsetTop || 0 }, { width, placement, align }));
  }, [trigger, panel, width, placement, align]);
  useLayoutEffect(() => {
    if (!open || !panel.current) { setPosition(null); return undefined; }
    const node = panel.current;
    if (node.showPopover && !node.matches(":popover-open")) {
      try { node.showPopover(); } catch { dismissRef.current?.(); return undefined; }
    }
    locate();
    window.addEventListener("resize", locate);
    window.addEventListener("scroll", locate, true);
    window.visualViewport?.addEventListener("resize", locate);
    window.visualViewport?.addEventListener("scroll", locate);
    const observer = new ResizeObserver(locate); observer.observe(node);
    const authority = new MutationObserver(locate);
    for (let ancestor = trigger.current?.parentElement; ancestor; ancestor = ancestor.parentElement) {
      authority.observe(ancestor, { attributes: true, attributeFilter: ["hidden", "inert", "open", "class", "style"] });
    }
    return () => {
      observer.disconnect(); authority.disconnect(); window.removeEventListener("resize", locate); window.removeEventListener("scroll", locate, true);
      window.visualViewport?.removeEventListener("resize", locate); window.visualViewport?.removeEventListener("scroll", locate);
      if (node.hidePopover && node.matches(":popover-open")) node.hidePopover();
    };
  }, [open, locate, panel]);
  return { position: "fixed", margin: 0, right: "auto", bottom: "auto", transform: "none",
    width: position?.width || width, left: position?.left || 0, top: position?.top || 0,
    maxHeight: position?.maxHeight || "calc(100dvh - 24px)", visibility: position ? "visible" : "hidden" };
}

export function leaveMenuWithTab(event, trigger, panel, close) {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  event.preventDefault();
  const scope = trigger.current?.closest("dialog[open]") || document;
  const candidates = [...scope.querySelectorAll("a[href],button,input,textarea,select,[tabindex]")]
    .filter(node => node.tabIndex >= 0 && !node.disabled && !node.closest("[hidden],[inert]")
      && getComputedStyle(node).visibility !== "hidden" && node.getClientRects().length && !panel.current?.contains(node));
  const index = candidates.indexOf(trigger.current), direction = event.shiftKey ? -1 : 1;
  const next = candidates[(index + direction + candidates.length) % candidates.length];
  close(false);
  queueMicrotask(() => (next || trigger.current)?.focus({ preventScroll: true }));
}
