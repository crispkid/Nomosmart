"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import {
  BookOpenText,
  CheckSquare,
  ChevronsUpDown,
  Database,
  Gauge,
  Home,
  LayoutDashboard,
  Lock,
  LogOut,
  Settings,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { NotificationCenter } from "./NotificationCenter";
import { feedbackIcons } from "./FeedbackMessage";
import { BrandMark } from "./BrandMark";
import { isSupportedLocale, supportedLocales, useI18n, type TranslationKey } from "@/lib/i18nClient";
import { visibleWorkspaceNav, workspaceArea } from "@/lib/workspaceNavigation";
import { BrowserTitle } from "@/lib/browserTitle";
import { getApprovalSummary } from "@/lib/apiClient/projectRequests";
import { useReadResource } from "@/lib/useReadResource";
import { applyThemePreference, readThemePreference, themePreferences, writeThemePreference, type ThemePreference } from "@/lib/theme";
import { MobileTabBar, SidebarNavigation, type NavigationItem } from "./WorkspaceNavigation";

const WorkspaceChromeContext = createContext(false);

/**
 * Workspace page header: browser title and the page heading (OPT424-035). Inside the
 * (workspace) route-group layout the navigation chrome is already mounted and persists across
 * navigation; rendered anywhere else, the page brings its own chrome as before.
 */
export function AppShell({ children, title, browserTitle, breadcrumb, titleAdornment, subtitle, actions }: {
  children: React.ReactNode; title: string; browserTitle?: string;
  /** CHG-495 M15 (DESIGN.md §6): breadcrumb above the heading; the last item is the current page. */
  breadcrumb?: { label: string; href?: string }[];
  titleAdornment?: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode;
}) {
  const insideChrome = useContext(WorkspaceChromeContext);
  const { authReady } = useAuth();
  const { t } = useI18n();
  const page = <><BrowserTitle label={authReady ? browserTitle ?? title : t("brandKnowledgeOps")} />
    <header className={actions ? "topbar has-actions" : "topbar"}>
      <div className="topbar-heading">
        {breadcrumb?.length ? <nav aria-label={t("breadcrumbLabel")} className="ws-breadcrumb"><ol>
          {breadcrumb.map((item, index) => <li key={`${index}:${item.label}`}>{item.href ? <Link href={item.href}>{item.label}</Link> : <span aria-current={index === breadcrumb.length - 1 ? "page" : undefined}>{item.label}</span>}</li>)}
        </ol></nav> : null}
        <h1>{titleAdornment}{title}</h1>
        {subtitle ? <p className="topbar-subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="topbar-actions">{actions}</div> : null}
    </header>
    {children}</>;
  return insideChrome ? page : <WorkspaceChrome>{page}</WorkspaceChrome>;
}

const themeLabelKeys: Record<ThemePreference, TranslationKey> = { system: "themeSystem", light: "themeLight", dark: "themeDark" };

/** CHG-495 UIRD-001: the stored theme choice; storage failures fall back to following the system. */
const themeListeners = new Set<() => void>();
let themeChoice: ThemePreference | null = null;
function browserStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}
function subscribeTheme(listener: () => void) {
  themeListeners.add(listener);
  return () => { themeListeners.delete(listener); };
}
function themeSnapshot(): ThemePreference {
  return themeChoice ?? readThemePreference(browserStorage());
}

export function useThemePreference(): [ThemePreference, (next: ThemePreference) => void] {
  const preference = useSyncExternalStore(subscribeTheme, themeSnapshot, () => "system" as ThemePreference);
  const choose = useCallback((next: ThemePreference) => {
    writeThemePreference(browserStorage(), next);
    applyThemePreference(document.documentElement, next);
    themeChoice = next;
    themeListeners.forEach(listener => listener());
  }, []);
  return [preference, choose];
}

const mobileQuery = "(max-width: 768px)";
function subscribeMobile(listener: () => void) {
  const query = window.matchMedia(mobileQuery);
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}
/** Mobile layout follows the 768px breakpoint; the server renders the desktop shell. */
function useMobileLayout(): boolean {
  return useSyncExternalStore(subscribeMobile, () => window.matchMedia(mobileQuery).matches, () => false);
}

/** Language, theme and sign-out controls shared by the sidebar account menu and the mobile "More" sheet. */
function AccountControls({ onDone }: { onDone?: () => void }) {
  const { currentUser, logout, userDisplayName } = useAuth();
  const { locale, setLocale, t } = useI18n();
  const department = currentUser?.department?.trim();
  const [theme, setTheme] = useThemePreference();
  const [loggingOut, setLoggingOut] = useState(false);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    onDone?.();
    await logout();
  }

  return <div className="ws-account-controls">
    <div className="ws-account-identity"><strong>{userDisplayName}</strong>{department ? <span>{department}</span> : null}</div>
    <div className="ws-account-group" role="group" aria-label={t("languageSwitcher")}>
      <span className="ws-account-group-label">{t("languageSwitcher")}</span>
      <div className="ws-segmented">
        {supportedLocales.map(item => (
          <button key={item.code} type="button" aria-pressed={locale === item.code} onClick={() => { if (isSupportedLocale(item.code)) setLocale(item.code); }}>{item.label}</button>
        ))}
      </div>
    </div>
    <div className="ws-account-group" role="group" aria-label={t("themeMenu")}>
      <span className="ws-account-group-label">{t("themeMenu")}</span>
      <div className="ws-segmented">
        {themePreferences.map(item => (
          <button key={item} type="button" aria-pressed={theme === item} onClick={() => setTheme(item)}>{t(themeLabelKeys[item])}</button>
        ))}
      </div>
    </div>
    <button className="ws-account-logout" disabled={loggingOut} onClick={handleLogout} type="button">
      <LogOut size={16} aria-hidden />
      <span>{loggingOut ? t("loggingOut") : t("logout", locale)}</span>
    </button>
  </div>;
}

function initialOf(name: string): string {
  return Array.from(name.trim())[0]?.toUpperCase() ?? "?";
}

/** CHG-495 UIRD-002: sidebar (desktop) or top bar and bottom tabs (mobile), plus the main landmark. */
export function WorkspaceChrome({ children }: { children: React.ReactNode }) {
  const { apiFetch, can, currentUser, userDisplayName } = useAuth();
  const department = currentUser?.department?.trim();
  const pathname = usePathname();
  const activeArea = workspaceArea(pathname);
  const shellRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const accountRef = useRef<HTMLDivElement>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const mobile = useMobileLayout();
  const { t, format } = useI18n();

  // M04: the review workspace shows how many reviews wait for the signed-in user.
  const readSummary = useCallback((signal: AbortSignal) => getApprovalSummary((input, init) => apiFetch(input, { ...init, signal })), [apiFetch]);
  const summary = useReadResource(readSummary, `approval-summary:${pathname}`, true, { keepData: true });
  const pending = summary.status === "error" ? null : summary.data?.pending_total ?? null;

  const navIcons: Record<string, NavigationItem["icon"]> = { "/": LayoutDashboard, "/projects": Database, "/approve": CheckSquare, "/reports": Gauge, "/system": Settings, "/api-docs": BookOpenText };
  const visibleItems: NavigationItem[] = visibleWorkspaceNav(menu => can("Menu", menu, "view")).map(entry => ({
    href: entry.href,
    label: t(entry.labelKey),
    shortLabel: entry.shortKey ? t(entry.shortKey) : undefined,
    icon: navIcons[entry.href],
    ...(entry.href === "/approve" ? { badge: pending, badgeLabel: pending ? format("navApprovalPendingCount", { count: pending }) : undefined } : {}),
  }));

  useEffect(() => {
    if (!accountOpen) return;
    const outside = (event: PointerEvent) => { if (accountRef.current && !accountRef.current.contains(event.target as Node)) setAccountOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setAccountOpen(false); };
    window.addEventListener("pointerdown", outside);
    window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("pointerdown", outside); window.removeEventListener("keydown", escape); };
  }, [accountOpen]);

  const brand = <Link className="ws-brand" href="/" aria-label={t("headerHomeLink")}><BrandMark size={22} /><span>NomoSmart</span></Link>;

  return (
    <WorkspaceChromeContext.Provider value={true}><div className="app-shell ws-shell" ref={shellRef}>
      <a className="skip-to-content" href="#workspace-main" onClick={() => mainRef.current?.focus()}>{t("skipToMainContent")}</a>
      {mobile ? null : <aside className="ws-sidebar" key="sidebar">
        <div className="ws-sidebar-top">{brand}<NotificationCenter /></div>
        <SidebarNavigation items={visibleItems} activeArea={activeArea} />
        <div className="ws-account" ref={accountRef}>
          <button className="ws-account-trigger" type="button" aria-expanded={accountOpen} aria-haspopup="true" aria-label={format("headerAccountMenu", { name: userDisplayName })} onClick={() => setAccountOpen(open => !open)}>
            <span className="ws-avatar" aria-hidden>{initialOf(userDisplayName)}</span>
            <span className="ws-account-name"><span>{userDisplayName}</span>{department ? <small>{department}</small> : null}</span>
            <ChevronsUpDown size={15} aria-hidden />
          </button>
          {accountOpen ? <div className="ws-account-panel"><AccountControls onDone={() => setAccountOpen(false)} /></div> : null}
        </div>
      </aside>}
      <div className="ws-body">
        {mobile ? <header className="ws-mobile-header">
          {brand}
          <div className="ws-mobile-tools">
            <NotificationCenter />
            <button className="ws-avatar-button" type="button" aria-label={format("headerAccountMenu", { name: userDisplayName })} onClick={() => setMoreOpen(true)}>
              <span className="ws-avatar" aria-hidden>{initialOf(userDisplayName)}</span>
            </button>
          </div>
        </header> : null}
        <main className="main" id="workspace-main" ref={mainRef} tabIndex={-1}>
          {children}
        </main>
        {mobile ? <MobileTabBar items={visibleItems} activeArea={activeArea} shellRef={shellRef} account={<AccountControls />} open={moreOpen} onOpenChange={setMoreOpen} /> : null}
      </div>
    </div></WorkspaceChromeContext.Provider>
  );
}

/** K041 (CHG-495 S01): centred card in the main area; the navigation stays available. */
export function ForbiddenState({ title, description }: { title?: string; description?: string }) {
  const { t } = useI18n();
  const titleId = useId();
  return (
    <section className="forbidden-state state-card" role="status" aria-labelledby={titleId}>
      <span className="state-card-icon tone-danger"><Lock aria-hidden="true" size={24} /></span>
      <h2 id={titleId}>{title ?? t("forbiddenTitle")}</h2>
      <p className="state-card-description">{description ?? t("forbiddenDescription")}</p>
      <div className="state-card-actions"><Link className="action-button" href="/"><Home aria-hidden="true" size={16} />{t("recoveryHome")}</Link></div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  helper,
  note,
  tone = "green"
}: {
  label: string;
  value: string;
  helper: string;
  /** CHG-495 M07: an optional second line that needs attention (for example overdue reviews). */
  note?: string;
  tone?: "green" | "gold" | "coral" | "sage" | "violet" | "neutral";
}) {
  return (
    <section className={`stat-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{helper}</small>
      {note ? <small className="stat-card-note">{note}</small> : null}
    </section>
  );
}

const statusLabelKeys: Record<string, TranslationKey> = {
  queued: "statusQueued",
  pending: "statusPending",
  passed: "statusPassed",
  needs_review: "statusNeedsReview",
  error: "statusError",
  partial_failed: "statusPartialFailed",
  cancelled: "statusCancelled",
  running: "statusRunning",
  processing: "statusProcessing",
  submission_ready: "statusSubmissionReady",
  awaiting_confirmation: "statusAwaitingConfirmation",
  pending_manager_review: "statusPendingManagerReview",
  pending_owner_review: "statusPendingOwnerReview",
  approved: "statusApproved",
  publish_ready: "statusPublishReady",
  publishing: "statusPublishing",
  production_indexing: "statusProductionIndexing",
  graph_syncing: "statusGraphSyncing",
  published_active: "statusPublishedActive",
  completed: "statusCompleted",
  waiting_action: "statusWaitingAction",
  failed: "statusFailed",
  skipped: "statusSkipped",
  active: "statusActive",
  inactive: "statusInactive",
  deleted: "statusDeleted",
  review_rejected: "statusReviewRejected"
};

/** CHG-449 DISP449-001: localized text of a status value, shared by the badge and plain status text. */
export function statusLabel(status: string, t: (key: TranslationKey) => string): string {
  const key = statusLabelKeys[status];
  return key ? t(key) : t("feedbackStatusUnknown");
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const tone = ["failed", "review_rejected", "deleted"].includes(status) ? "error" : ["completed", "approved", "published_active", "active", "submission_ready", "publish_ready", "skipped"].includes(status) ? "success" : status === "inactive" || !statusLabelKeys[status] ? "warning" : "info";
  const Icon = feedbackIcons[tone];
  return <span className={`status-badge feedback-status-badge feedback-${tone}`}><Icon size={14} aria-hidden="true" />{statusLabel(status, t)}</span>;
}

export type BadgeTone = "accent" | "info" | "amber" | "danger" | "violet" | "neutral";

/** CHG-495 UIRD-004 badge: soft background, ink text and a dot; the text always carries the meaning. */
export function ToneBadge({ tone, children, className }: { tone: BadgeTone; children: React.ReactNode; className?: string }) {
  return <span className={`ws-badge tone-${tone}${className ? ` ${className}` : ""}`}><i aria-hidden="true" />{children}</span>;
}

export function PageGrid({ children }: { children: React.ReactNode }) {
  return <div className="page-grid">{children}</div>;
}

export function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
