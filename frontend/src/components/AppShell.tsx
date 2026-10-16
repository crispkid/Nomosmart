"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  BookOpenText,
  ChevronDown,
  CheckSquare,
  Database,
  Gauge,
  LayoutDashboard,
  LogOut,
  Languages,
  Search,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { NotificationCenter } from "./NotificationCenter";
import { FeedbackMessage, feedbackIcons } from "./FeedbackMessage";
import { isSupportedLocale, supportedLocales, useI18n } from "@/lib/i18nClient";

export function AppShell({ children, title }: { children: React.ReactNode; title: string }) {
  const { can, logout, userDisplayName } = useAuth();
  const [languageMenuOpen, setLanguageMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const { locale, setLocale, t } = useI18n();
  const languageMenuRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const navItems = [
    { href: "/", label: t("home"), icon: LayoutDashboard, visible: true },
    { href: "/projects", label: t("dashboard"), icon: Database, visible: can("Menu", "KnowledgeProjects", "view") },
    { href: "/approve", label: t("approval"), icon: CheckSquare, visible: true },
    { href: "/reports", label: t("reports"), icon: Gauge, visible: can("Menu", "Reports", "view") },
    { href: "/system", label: t("system"), icon: Settings, visible: can("Menu", "SystemManagement", "view") },
    { href: "/api-docs", label: t("apiDocs"), icon: BookOpenText, visible: true }
  ];

  useEffect(() => {
    function closeOnOutside(event: PointerEvent) {
      if (languageMenuRef.current && !languageMenuRef.current.contains(event.target as Node)) setLanguageMenuOpen(false);
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setUserMenuOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setLanguageMenuOpen(false);
        setUserMenuOpen(false);
      }
    }
    window.addEventListener("pointerdown", closeOnOutside);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutside);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setUserMenuOpen(false);
    await logout();
  }

  function switchLocale(nextLocale: string) {
    if (!isSupportedLocale(nextLocale)) return;
    setLocale(nextLocale);
    setLanguageMenuOpen(false);
  }

  const activeLocale = supportedLocales.find((item) => item.code === locale) ?? supportedLocales[0];

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" href="/">
          <span className="brand-mark">N</span>
          <span>
            <strong>NomoSmart</strong>
            <small>{t("brandKnowledgeOps")}</small>
          </span>
        </Link>
        <nav className="nav-list" aria-label={t("primaryNavigation")}>
          {navItems.filter((item) => item.visible).map((item) => {
            const Icon = item.icon;
            return (
              <Link className="nav-item" href={item.href} key={item.href}>
                <Icon size={18} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="header-tools">
          <label className="search-box">
            <Search size={17} />
            <input placeholder={t("search")} />
          </label>
          <div className="language-switcher user-menu" ref={languageMenuRef}>
            <button aria-expanded={languageMenuOpen} aria-haspopup="menu" aria-label={t("languageSwitcher")} className="user-pill language-switcher-trigger" onClick={() => setLanguageMenuOpen((open) => !open)} type="button">
              <Languages size={17} />
              <span>{activeLocale.label}</span>
              <ChevronDown size={15} />
            </button>
            {languageMenuOpen ? (
              <div className="user-menu-panel language-menu-panel" role="menu">
                {supportedLocales.map((item) => (
                  <button aria-checked={locale === item.code} className={locale === item.code ? "active" : ""} key={item.code} onClick={() => switchLocale(item.code)} role="menuitemradio" type="button">
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <NotificationCenter />
          <div className="user-menu" ref={menuRef}>
            <button aria-expanded={userMenuOpen} aria-haspopup="menu" className="user-pill" onClick={() => setUserMenuOpen((open) => !open)} type="button">
              <ShieldCheck size={17} />
              <span>{userDisplayName}</span>
              <ChevronDown size={15} />
            </button>
            {userMenuOpen ? (
              <div className="user-menu-panel" role="menu">
                <button disabled={loggingOut} onClick={handleLogout} role="menuitem" type="button">
                  <LogOut size={16} />
                  <span>{loggingOut ? t("loggingOut") : t("logout", locale)}</span>
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main className="main">
        <header className="topbar">
          <div>
            <h1>{title}</h1>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

export function ForbiddenState({ title, description }: { title?: string; description?: string }) {
  const { t } = useI18n();
  return (
    <FeedbackMessage tone="warning" title={title ?? t("forbiddenTitle")}>{description ?? t("forbiddenDescription")}</FeedbackMessage>
  );
}

export function StatCard({
  label,
  value,
  helper,
  tone = "green"
}: {
  label: string;
  value: string;
  helper: string;
  tone?: "green" | "gold" | "coral" | "sage";
}) {
  return (
    <section className={`stat-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{helper}</small>
    </section>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const labels: Record<string, ReturnType<typeof t>> = {
    queued: t("statusQueued"),
    running: t("statusRunning"),
    processing: t("statusProcessing"),
    submission_ready: t("statusSubmissionReady"),
    pending_manager_review: t("statusPendingManagerReview"),
    pending_owner_review: t("statusPendingOwnerReview"),
    approved: t("statusApproved"),
    publish_ready: t("statusPublishReady"),
    publishing: t("statusPublishing"),
    production_indexing: t("statusProductionIndexing"),
    graph_syncing: t("statusGraphSyncing"),
    published_active: t("statusPublishedActive"),
    completed: t("statusCompleted"),
    waiting_action: t("statusWaitingAction"),
    failed: t("statusFailed"),
    skipped: t("statusSkipped"),
    active: t("statusActive"),
    inactive: t("statusInactive"),
    deleted: t("statusDeleted"),
    review_rejected: t("statusReviewRejected")
  };
  const tone = ["failed", "review_rejected", "deleted"].includes(status) ? "error" : ["completed", "approved", "published_active", "active", "submission_ready", "publish_ready", "skipped"].includes(status) ? "success" : status === "inactive" || !labels[status] ? "warning" : "info";
  const Icon = feedbackIcons[tone];
  return <span className={`status-badge feedback-status-badge feedback-${tone}`}><Icon size={14} aria-hidden="true" />{labels[status] ?? t("feedbackStatusUnknown")}</span>;
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

export function ActionButton({ children, variant = "primary" }: { children: React.ReactNode; variant?: "primary" | "secondary" | "danger" }) {
  return <button className={`action-button ${variant}`}>{children}</button>;
}
