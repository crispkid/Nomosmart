"use client";

import { Children, Fragment, isValidElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ChangeEvent, type CSSProperties, type KeyboardEvent, type ReactNode, type SelectHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "multiple" | "size">;
type Option = { value: string; label: string; disabled: boolean };
type OptionProps = { value?: string | number; label?: string; disabled?: boolean; children?: ReactNode };

function optionText(children: ReactNode): string {
  return Children.toArray(children).map(child => typeof child === "string" || typeof child === "number" ? String(child)
    : isValidElement<OptionProps>(child) ? optionText(child.props.children) : "").join("");
}

function readOptions(children: ReactNode, groupDisabled = false): Option[] {
  const result: Option[] = [];
  Children.forEach(children, child => {
    if (!isValidElement<OptionProps>(child)) return;
    if (child.type === Fragment || child.type === "optgroup") result.push(...readOptions(child.props.children, groupDisabled || Boolean(child.props.disabled)));
    else if (child.type === "option") {
      const text = optionText(child.props.children);
      result.push({ value: String(child.props.value ?? text), label: child.props.label ?? text, disabled: groupDisabled || Boolean(child.props.disabled) });
    }
  });
  return result;
}

/** Custom presentation, with the actual select retained only for form semantics. */
export function DropdownSelect({ children, className, id, value, defaultValue, disabled, autoFocus, onChange, onInvalid, onFocus, onBlur, ...attributes }: Props) {
  const { t } = useI18n();
  const generatedId = useId();
  const controlId = id ?? `app-select-${generatedId}`;
  const listId = `${controlId}-options`;
  const nativeRef = useRef<HTMLSelectElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLSpanElement>(null);
  const typed = useRef({ text: "", time: 0 });
  const options = readOptions(children);
  const controlled = value !== undefined;
  const [localValue, setLocalValue] = useState(() => String(defaultValue ?? options.find(option => !option.disabled)?.value ?? ""));
  const committed = controlled ? String(value) : localValue;
  const selected = options.find(option => option.value === committed);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [fieldsetDisabled, setFieldsetDisabled] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({});
  const unavailable = Boolean(disabled || fieldsetDisabled);

  const close = useCallback((returnFocus = false) => {
    setOpen(false);
    typed.current.text = "";
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  const placePanel = useCallback(() => {
    const button = triggerRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 184), window.innerWidth - 16);
    const below = Math.max(0, window.innerHeight - rect.bottom - 16);
    const above = Math.max(0, rect.top - 16);
    const flip = below < Math.min(132, options.length * 44 + 14) && above > below;
    const maxHeight = Math.min(320, Math.max(44, flip ? above : below), options.length * 44 + 14);
    setPosition({ width, maxHeight, left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)), top: flip ? Math.max(8, rect.top - maxHeight - 8) : rect.bottom + 8 });
  }, [options.length]);

  function show(preferred?: number) {
    if (nativeRef.current?.matches(":disabled") || !options.some(option => !option.disabled)) return;
    const current = options.findIndex(option => option.value === committed && !option.disabled);
    setActive(preferred ?? (current >= 0 ? current : options.findIndex(option => !option.disabled)));
    placePanel();
    setOpen(true);
  }

  function choose(index: number) {
    const native = nativeRef.current;
    const option = options[index];
    if (!native || native.matches(":disabled") || !option || option.disabled) return;
    if (native.value !== option.value) {
      native.value = option.value;
      native.dispatchEvent(new Event("change", { bubbles: true }));
    }
    close(true);
  }

  function move(direction: 1 | -1) {
    let index = active;
    for (let step = 0; step < options.length; step++) {
      index = (index + direction + options.length) % options.length;
      if (!options[index].disabled) { setActive(index); break; }
    }
  }

  function handleKey(event: KeyboardEvent<HTMLElement>) {
    if (event.nativeEvent.isComposing || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "Escape") {
      if (open) { event.preventDefault(); event.stopPropagation(); close(true); }
    } else if (event.key === "Tab") close();
    else if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      if (!open) show(event.key === "End" ? options.findLastIndex(option => !option.disabled) : event.key === "Home" ? options.findIndex(option => !option.disabled) : undefined);
      else if (event.key === "Enter" || event.key === " ") choose(active);
      else if (event.key === "Home") setActive(options.findIndex(option => !option.disabled));
      else if (event.key === "End") setActive(options.findLastIndex(option => !option.disabled));
      else move(event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key.length === 1 && event.key.trim()) {
      const now = Date.now();
      typed.current = { text: (now - typed.current.time < 700 ? typed.current.text : "") + event.key.toLocaleLowerCase(), time: now };
      const match = options.findIndex(option => !option.disabled && option.label.toLocaleLowerCase().startsWith(typed.current.text));
      if (match >= 0) { event.preventDefault(); show(match); }
    }
  }

  useEffect(() => {
    const native = nativeRef.current;
    if (!native) return;
    const fieldsets: HTMLFieldSetElement[] = [];
    for (let parent = native.parentElement; parent; parent = parent.parentElement) if (parent instanceof HTMLFieldSetElement) fieldsets.push(parent);
    const sync = () => {
      const blocked = native.matches(":disabled");
      setFieldsetDisabled(blocked && !native.disabled);
      if (blocked) setOpen(false);
      if (!controlled) setLocalValue(native.value);
    };
    const observer = new MutationObserver(sync);
    fieldsets.forEach(fieldset => observer.observe(fieldset, { attributes: true, attributeFilter: ["disabled"] }));
    observer.observe(native, { attributes: true, attributeFilter: ["disabled"], childList: true, subtree: true, characterData: true });
    queueMicrotask(sync);
    const form = native.form;
    let resetTimer: number | undefined;
    const reset = (event: Event) => {
      window.clearTimeout(resetTimer);
      // Browser reset is a default action, after the reset event dispatch.
      resetTimer = window.setTimeout(() => {
        if (event.defaultPrevented) return;
        if (controlled) native.value = String(value);
        else setLocalValue(native.value);
        setInvalid(false);
        setOpen(false);
      }, 0);
    };
    form?.addEventListener("reset", reset);
    return () => { observer.disconnect(); form?.removeEventListener("reset", reset); window.clearTimeout(resetTimer); };
  }, [controlled, value]);

  useLayoutEffect(() => {
    const button = triggerRef.current;
    if (!button || attributes["aria-label"] || attributes["aria-labelledby"]) return;
    const labels = Array.from(button.labels ?? []).map(label => {
      const copy = label.cloneNode(true) as HTMLElement;
      copy.querySelectorAll("[data-app-select-root]").forEach(control => control.remove());
      return copy.textContent?.trim() ?? "";
    }).filter(Boolean).join(" ");
    if (labels) button.setAttribute("aria-label", labels);
  });

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node) && !panelRef.current?.contains(event.target as Node)) close();
    };
    const reposition = (event: Event) => {
      if (!panelRef.current?.contains(event.target as Node)) placePanel();
    };
    document.addEventListener("pointerdown", outside);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    const observer = new ResizeObserver(() => placePanel());
    if (triggerRef.current) observer.observe(triggerRef.current);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      observer.disconnect();
    };
  }, [open, placePanel, close]);

  useLayoutEffect(() => {
    if (open && active >= 0) panelRef.current?.querySelector<HTMLElement>(`[data-option-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  function changed(event: ChangeEvent<HTMLSelectElement>) {
    if (!controlled) setLocalValue(event.currentTarget.value);
    if (event.currentTarget.validity.valid) setInvalid(false);
    onChange?.(event);
  }

  return <span className="app-select" data-app-select-root ref={rootRef}>
    <button aria-activedescendant={open && active >= 0 && options[active] ? `${listId}-${active}` : undefined} aria-controls={open ? listId : undefined} aria-describedby={[attributes["aria-describedby"], invalid ? `${controlId}-error` : null].filter(Boolean).join(" ") || undefined} aria-expanded={open} aria-haspopup="listbox" aria-invalid={attributes["aria-invalid"] ?? (invalid || undefined)} aria-label={attributes["aria-label"]} aria-labelledby={attributes["aria-labelledby"]} aria-required={attributes.required || undefined} autoFocus={autoFocus} className={["app-select-trigger", className].filter(Boolean).join(" ")} data-value={committed} disabled={unavailable} id={controlId} onBlur={event => {
      if (!panelRef.current?.contains(event.relatedTarget as Node | null)) close();
    }} onClick={() => open ? close() : show()} onKeyDown={handleKey} ref={triggerRef} role="combobox" title={attributes.title ?? selected?.label} type="button" value={committed}>
      <span className="app-select-value">{(selected?.label ?? options.find(option => option.value === "")?.label ?? committed) || "\u00a0"}</span><ChevronDown aria-hidden size={16} />
    </button>
    <select {...attributes} aria-hidden="true" autoFocus={false} className="app-select-native" data-app-select-bridge={controlId} defaultValue={defaultValue} disabled={disabled} hidden id={`${controlId}-native`} onBlur={onBlur} onChange={changed} onFocus={onFocus} onInvalid={event => {
      event.preventDefault();
      setInvalid(true);
      triggerRef.current?.focus();
      onInvalid?.(event);
    }} ref={nativeRef} tabIndex={-1} value={value}>{children}</select>
    {invalid ? <span className="field-error app-select-error" id={`${controlId}-error`}>{t("feedbackFieldRequired")}</span> : null}
    {open && !unavailable && createPortal(<div className="app-select-options" id={listId} onKeyDown={handleKey} ref={panelRef} role="listbox" aria-labelledby={controlId} style={position}>
      {options.map((option, index) => <button aria-disabled={option.disabled || undefined} aria-selected={option.value === committed} className={`app-select-option${option.value === committed ? " is-selected" : ""}${index === active ? " is-active" : ""}`} data-option-index={index} data-option-value={option.value} disabled={option.disabled || unavailable} id={`${listId}-${index}`} key={`${index}-${option.value}`} onClick={() => choose(index)} onMouseDown={event => event.preventDefault()} onPointerMove={() => { if (!option.disabled) setActive(index); }} role="option" tabIndex={-1} type="button"><span>{option.label}</span>{option.value === committed ? <Check aria-hidden size={17} /> : <span className="app-select-check-space" aria-hidden />}</button>)}
    </div>, document.body)}
  </span>;
}
