import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { advertisedModels, matchMenuText, moveMenuIndex } from "./menuPolicy.js";
import { leaveMenuWithTab, useMenuSurface } from "./useMenuSurface.js";
import "../../styles/menus-refined.css";

export default function ModelSelector({ models = [], selectedModelId, onSelectModel, disabled = false, placement = "above" }) {
  const options = useMemo(() => advertisedModels(models), [models]);
  const [open, setOpen] = useState(false), [active, setActive] = useState(0);
  const id = useId(), root = useRef(null), trigger = useRef(null), panel = useRef(null), items = useRef([]);
  const search = useRef({ value: "", time: 0 });
  const selected = options.find(model => model.id === selectedModelId);
  const selectedIndex = Math.max(0, options.findIndex(model => model.id === selectedModelId));
  const close = (restore = false) => {
    setOpen(false); search.current = { value: "", time: 0 };
    if (restore) trigger.current?.focus({ preventScroll: true });
  };
  const style = useMenuSurface(open, trigger, panel, { width: 340, placement, dismiss: close });
  const show = (index = selectedIndex) => { if (disabled || !options.length) return; setActive(index); setOpen(true); };
  useLayoutEffect(() => {
    if (!open || style.visibility !== "visible") return;
    const index = Math.min(active, options.length - 1);
    if (index !== active) setActive(index);
    items.current[index]?.focus({ preventScroll: true }); items.current[index]?.scrollIntoView({ block: "nearest" });
  }, [open, active, options, style.visibility]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = event => { if (!root.current?.contains(event.target)) close(); };
    document.addEventListener("pointerdown", outside, true); document.addEventListener("focusin", outside, true);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("focusin", outside, true); };
  }, [open]);
  useEffect(() => { if (disabled || !options.length) close(); }, [disabled, options.length]);
  const keyboard = event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); return; }
    if (event.key === "Tab") { leaveMenuWithTab(event, trigger, panel, close); return; }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault(); setActive(moveMenuIndex(event.key, active, options.map((_, index) => index))); return;
    }
    if (event.key.length !== 1 || event.key === " " || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return;
    event.preventDefault(); const now = Date.now();
    const value = (now - search.current.time < 650 ? search.current.value : "") + event.key.toLocaleLowerCase();
    search.current = { value: value.slice(-80), time: now };
    setActive(matchMenuText(options.map(model => model.name), search.current.value, active));
  };
  return <div className="model-selector model-selector--refined" ref={root} data-model-menu-open={open ? "true" : undefined}>
    <span className="model-selector__label" id={`${id}-label`}>AI model</span>
    <button ref={trigger} type="button" className="model-selector__trigger" aria-haspopup="menu" aria-expanded={open}
      aria-controls={open ? `${id}-menu` : undefined} aria-labelledby={`${id}-label ${id}-name`}
      title={selected?.name} disabled={disabled || !options.length} onClick={() => open ? close(true) : show()}
      onKeyDown={event => { if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault(); show(event.key === "ArrowUp" ? options.length - 1 : 0);
      } }}>
      <svg className="model-selector__symbol" viewBox="0 0 20 20" aria-hidden="true"><path d="m10 2 1.8 5.7L18 10l-6.2 2.3L10 18l-1.8-5.7L2 10l6.2-2.3Z" /></svg>
      <span className="model-selector__name" id={`${id}-name`}>{selected?.name || (options.length ? "Choose a model" : "Models unavailable")}</span>
      <svg className="model-selector__chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m5 7.5 5 5 5-5" /></svg>
    </button>
    {open && <div ref={panel} popover="manual" style={style} className="model-selector__menu" id={`${id}-menu`} role="menu" aria-label="AI models" aria-describedby={`${id}-note`} onKeyDown={keyboard}>
      <div className="model-selector__heading" role="presentation"><strong>Choose your model</strong><span>For your next question</span></div>
      {options.map((model, index) => <button key={model.id} type="button" role="menuitemradio" className="model-selector__option"
        data-model-id={model.id} aria-checked={model.id === selectedModelId} tabIndex={index === active ? 0 : -1}
        ref={element => { items.current[index] = element; }} onFocus={() => setActive(index)} onClick={() => {
          if (model.id !== selectedModelId) onSelectModel?.(model.id); close(true);
        }}>
        <span className="model-selector__option-copy"><span className="model-selector__option-name">{model.name}</span>
          {model.description && <span className="model-selector__description">{model.description}</span>}</span>
        <span className="model-selector__selection" aria-hidden="true">{model.id === selectedModelId && <svg className="model-selector__check" viewBox="0 0 20 20"><path d="m4.5 10 3.5 3.5 7.5-7.5" /></svg>}</span>
      </button>)}
      <p className="model-selector__note" id={`${id}-note`}>Switching models won’t restart an answer already in progress.</p>
    </div>}
  </div>;
}
