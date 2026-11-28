"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { useEffect, useId, useLayoutEffect, type ReactNode, type RefObject } from "react";
import { MoreHorizontal, X, type LucideIcon } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";
import { useModalFocus } from "./useModalFocus";
import { splitMobileNav } from "@/lib/workspaceNavigation";

export type NavigationItem = { href: string; label: string; shortLabel?: string; icon: LucideIcon; badge?: number | null; badgeLabel?: string };


function CountBadge({ value, label }: { value?: number | null; label?: string }) {
  if (!value) return null;
  return <span className="ws-nav-badge" aria-label={label}>{value > 99 ? "99+" : value}</span>;
}

/** CHG-495 UIRD-002 (M01, M04): desktop sidebar links; items arrive already filtered by menu permission. */
export function SidebarNavigation({ items, activeArea }: { items: NavigationItem[]; activeArea: string | null }) {
  const { t } = useI18n();
  return <nav className="ws-sidebar-nav" aria-label={t("primaryNavigation")}>
    {items.map(item => {
      const Icon = item.icon;
      const active = activeArea === item.href;
      return <Link href={item.href} key={item.href} className={`ws-nav-link${active ? " active" : ""}`} aria-current={active ? "page" : undefined}>
        <Icon aria-hidden size={16} /><span>{item.label}</span><CountBadge value={item.badge} label={item.badgeLabel} />
      </Link>;
    })}
  </nav>;
}

function MoreSheet({ items, activeArea, shellRef, onClose, id, children }: { items: NavigationItem[]; activeArea: string | null; shellRef: RefObject<HTMLDivElement | null>; onClose: () => void; id: string; children: ReactNode }) {
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

  return <div className="ws-sheet-overlay" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="ws-sheet" id={id} ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <header className="ws-sheet-heading">
        <h2 id={`${id}-title`}>{t("headerMore")}</h2>
        <button className="ws-icon-button" type="button" aria-label={t("headerCloseNavigation")} onClick={onClose}><X aria-hidden size={20} /></button>
      </header>
      {items.length ? <nav className="ws-sheet-links" aria-label={t("headerNavigation")}>
        {items.map(item => {
          const Icon = item.icon;
          return <Link href={item.href} key={item.href} aria-current={activeArea === item.href ? "page" : undefined} onClick={onClose}>
            <Icon aria-hidden size={20} /><span>{item.label}</span>
          </Link>;
        })}
      </nav> : null}
      <div className="ws-sheet-account">{children}</div>
    </section>
  </div>;
}

/**
 * CHG-495 UIRD-002 (M02): mobile bottom tab bar with Home, Projects, Review and More. "More" holds
 * the remaining permitted areas and the account controls (language, theme, sign out).
 */
export function MobileTabBar({ items, activeArea, shellRef, account, open, onOpenChange }: { items: NavigationItem[]; activeArea: string | null; shellRef: RefObject<HTMLDivElement | null>; account: ReactNode; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useI18n();
  const id = useId();
  const { tabs, more } = splitMobileNav(items);
  const moreActive = more.some(item => item.href === activeArea);

  useEffect(() => () => onOpenChange(false), [onOpenChange]);

  return <>
    <nav className="ws-tabbar" aria-label={t("primaryNavigation")}>
      {tabs.map(item => {
        const Icon = item.icon;
        const active = activeArea === item.href;
        return <Link href={item.href} key={item.href} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}>
          <span className="ws-tab-icon"><Icon aria-hidden size={20} /><CountBadge value={item.badge} label={item.badgeLabel} /></span><span>{item.shortLabel ?? item.label}</span>
        </Link>;
      })}
      <button type="button" className={moreActive ? "active" : undefined} aria-haspopup="dialog" aria-expanded={open} aria-controls={`${id}-more`} onClick={() => onOpenChange(true)}>
        <span className="ws-tab-icon"><MoreHorizontal aria-hidden size={20} /></span><span>{t("headerMore")}</span>
      </button>
    </nav>
    {open ? createPortal(<MoreSheet items={more} activeArea={activeArea} shellRef={shellRef} onClose={() => onOpenChange(false)} id={`${id}-more`}>{account}</MoreSheet>, document.body) : null}
  </>;
}

export default SidebarNavigation;
