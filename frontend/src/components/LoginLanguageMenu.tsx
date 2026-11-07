"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown, Languages } from "lucide-react";
import { supportedLocales, useI18n, type Locale } from "@/lib/i18nClient";

export default function LoginLanguageMenu() {
  const { locale, setLocale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const initialFocus = useRef(0);
  const id = useId();
  const activeIndex = Math.max(0, supportedLocales.findIndex(item => item.code === locale));

  useEffect(() => {
    if (!open) return;
    optionRefs.current[initialFocus.current]?.focus();
    function closeOutside(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);

  function openAt(index: number) {
    initialFocus.current = index;
    if (open) optionRefs.current[index]?.focus();
    else setOpen(true);
  }

  function closeAndReturnFocus() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function chooseLocale(nextLocale: Locale) {
    setLocale(nextLocale);
    closeAndReturnFocus();
  }

  function handleMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" || event.key === "Tab" && event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      closeAndReturnFocus();
      return;
    }
    const current = optionRefs.current.findIndex(button => button === document.activeElement);
    const last = supportedLocales.length - 1;
    const next = event.key === "Home" ? 0 : event.key === "End" ? last
      : event.key === "ArrowDown" ? (current + 1) % supportedLocales.length
        : event.key === "ArrowUp" ? (current + last) % supportedLocales.length : null;
    if (next !== null) {
      event.preventDefault();
      optionRefs.current[next]?.focus();
    }
  }

  return <div className="login-language-menu" ref={containerRef} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }}>
    <button className="login-language-trigger" id={`${id}-trigger`} ref={triggerRef} type="button" aria-label={t("languageSwitcher")} aria-haspopup="menu" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => open ? setOpen(false) : openAt(activeIndex)} onKeyDown={event => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        openAt(event.key === "ArrowDown" ? 0 : supportedLocales.length - 1);
      } else if (event.key === "Escape" && open) {
        event.preventDefault();
        closeAndReturnFocus();
      }
    }}>
      <Languages aria-hidden size={18} /><span>{supportedLocales[activeIndex].label}</span><ChevronDown className="login-language-chevron" aria-hidden size={16} />
    </button>
    {open ? <div className="login-language-options" id={`${id}-options`} role="menu" aria-labelledby={`${id}-trigger`} onKeyDown={handleMenuKey}>
      {supportedLocales.map((item, index) => <button key={item.code} ref={node => { optionRefs.current[index] = node; }} className={locale === item.code ? "is-selected" : ""} role="menuitemradio" aria-checked={locale === item.code} tabIndex={-1} type="button" onClick={() => chooseLocale(item.code)}>
        <span>{item.label}</span>{locale === item.code ? <Check aria-hidden size={17} /> : null}
      </button>)}
    </div> : null}
  </div>;
}
