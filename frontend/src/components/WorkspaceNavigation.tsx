"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { ChevronDown, Menu, MoreHorizontal, X, type LucideIcon } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";
import { useModalFocus } from "./useModalFocus";

type NavigationItem = { href: string; label: string; icon: LucideIcon };
type NavigationProps = {
  items: NavigationItem[];
  activeArea: string | null;
  shellRef: RefObject<HTMLDivElement | null>;
};

function MobileNavigation({ items, activeArea, shellRef, onClose, id }: NavigationProps & { onClose: () => void; id: string }) {
  const { t } = useI18n();
  const dialogRef = useModalFocus(true, onClose);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    const wasInert = shell?.inert ?? false;
    const previousOverflow = document.body.style.overflow;
    if (shell) shell.inert = true;
    document.body.style.overflow = "hidden";
    return () => {
      if (shell) shell.inert = wasInert;
      document.body.style.overflow = previousOverflow;
    };
  }, [shellRef]);

  return <div className="workspace-mobile-overlay" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="workspace-mobile-drawer" id={id} ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <header className="workspace-mobile-heading">
        <h2 id={`${id}-title`}>{t("headerNavigation")}</h2>
        <button className="workspace-menu-close" type="button" aria-label={t("headerCloseNavigation")} onClick={onClose}><X aria-hidden size={20} /></button>
      </header>
      <nav className="workspace-mobile-links" aria-label={t("primaryNavigation")}>
        {items.map(item => {
          const Icon = item.icon;
          return <Link href={item.href} key={item.href} aria-current={activeArea === item.href ? "page" : undefined} onClick={onClose}>
            <Icon aria-hidden size={20} /><span>{item.label}</span>
          </Link>;
        })}
      </nav>
    </section>
  </div>;
}

export default function WorkspaceNavigation({ items, activeArea, shellRef }: NavigationProps) {
  const { t } = useI18n();
  const id = useId();
  const [moreOpen, setMoreOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const moreTrigger = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLAnchorElement | null>>([]);
  const initialFocus = useRef(0);
  const primary = items.filter(item => item.href === "/projects" || item.href === "/approve");
  const secondary = items.filter(item => item.href !== "/" && item.href !== "/projects" && item.href !== "/approve");
  const moreActive = secondary.some(item => item.href === activeArea);

  useEffect(() => {
    const boundary = window.matchMedia("(max-width: 768px)");
    const closeOnResize = () => { setMoreOpen(false); setMobileOpen(false); };
    boundary.addEventListener("change", closeOnResize);
    return () => boundary.removeEventListener("change", closeOnResize);
  }, []);

  useEffect(() => {
    if (!moreOpen) return;
    optionRefs.current[initialFocus.current]?.focus();
    const outside = (event: PointerEvent) => { if (!moreRef.current?.contains(event.target as Node)) setMoreOpen(false); };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [moreOpen]);

  function openMoreAt(index: number) {
    initialFocus.current = index;
    if (moreOpen) optionRefs.current[index]?.focus();
    else setMoreOpen(true);
  }

  function closeMoreAndFocus() {
    setMoreOpen(false);
    moreTrigger.current?.focus();
  }

  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" || event.key === "Tab" && event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      closeMoreAndFocus();
      return;
    }
    const current = optionRefs.current.findIndex(link => link === document.activeElement);
    const count = secondary.length;
    const next = event.key === "Home" ? 0 : event.key === "End" ? count - 1
      : event.key === "ArrowDown" ? (current + 1) % count
        : event.key === "ArrowUp" ? (current + count - 1) % count : null;
    if (next !== null) {
      event.preventDefault();
      optionRefs.current[next]?.focus();
    } else if (event.key === " " && current >= 0) {
      event.preventDefault();
      optionRefs.current[current]?.click();
    }
  }

  return <>
    <button className="workspace-mobile-trigger" type="button" aria-label={t("headerOpenNavigation")} aria-haspopup="dialog" aria-expanded={mobileOpen} aria-controls={`${id}-mobile`} onClick={() => setMobileOpen(true)}>
      <Menu aria-hidden size={21} />
    </button>
    <nav className="nav-list workspace-nav" aria-label={t("primaryNavigation")}>
      {primary.map(item => {
        const Icon = item.icon;
        return <Link href={item.href} key={item.href} className={`nav-item${activeArea === item.href ? " active" : ""}`} aria-current={activeArea === item.href ? "page" : undefined}>
          <Icon className="workspace-nav-icon" aria-hidden size={18} /><span>{item.label}</span>
        </Link>;
      })}
      {secondary.length ? <div className="workspace-more" ref={moreRef} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setMoreOpen(false); }}>
        <button className={`nav-item workspace-more-trigger${moreActive ? " active" : ""}`} type="button" id={`${id}-trigger`} ref={moreTrigger} aria-haspopup="menu" aria-expanded={moreOpen} aria-controls={`${id}-options`} onClick={() => moreOpen ? setMoreOpen(false) : openMoreAt(Math.max(0, secondary.findIndex(item => item.href === activeArea)))} onKeyDown={event => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            openMoreAt(event.key === "ArrowDown" ? 0 : secondary.length - 1);
          }
        }}>
          <MoreHorizontal className="workspace-nav-icon" aria-hidden size={18} /><span>{t("headerMore")}</span><ChevronDown className="workspace-more-chevron" aria-hidden size={14} />
        </button>
        {moreOpen ? <div className="workspace-more-panel" id={`${id}-options`} role="menu" aria-labelledby={`${id}-trigger`} onKeyDown={onMenuKey}>
          {secondary.map((item, index) => {
            const Icon = item.icon;
            return <Link href={item.href} key={item.href} ref={node => { optionRefs.current[index] = node; }} role="menuitem" tabIndex={-1} aria-current={activeArea === item.href ? "page" : undefined} onClick={() => setMoreOpen(false)}>
              <Icon aria-hidden size={18} /><span>{item.label}</span>
            </Link>;
          })}
        </div> : null}
      </div> : null}
    </nav>
    {mobileOpen ? createPortal(<MobileNavigation items={items} activeArea={activeArea} shellRef={shellRef} onClose={() => setMobileOpen(false)} id={`${id}-mobile`} />, document.body) : null}
  </>;
}
