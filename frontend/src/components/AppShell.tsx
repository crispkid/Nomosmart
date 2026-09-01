"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Bell,
  BookOpenText,
  ChevronDown,
  CheckSquare,
  Database,
  ExternalLink,
  Gauge,
  LayoutDashboard,
  LogOut,
  Languages,
  Search,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { getNotificationUnreadCount, listNotifications, markAllNotificationsRead, markNotificationRead, resolveNotification, type NotificationResponse } from "@/lib/api";
import { initializeLocale, isSupportedLocale, supportedLocales, useI18n, type TranslationKey } from "@/lib/i18nClient";

const notificationCopyKeys: Record<string, { title: TranslationKey; message: TranslationKey }> = {
  "review.manager.pending": { title: "notificationReviewManagerPendingTitle", message: "notificationReviewManagerPendingMessage" },
  "review.owner.pending": { title: "notificationReviewOwnerPendingTitle", message: "notificationReviewOwnerPendingMessage" },
  "review.approved": { title: "notificationReviewApprovedTitle", message: "notificationReviewApprovedMessage" },
  "review.rejected": { title: "notificationReviewRejectedTitle", message: "notificationReviewRejectedMessage" },
  "document.published": { title: "notificationDocumentPublishedTitle", message: "notificationDocumentPublishedMessage" },
  "document.active_switched": { title: "notificationDocumentActiveSwitchedTitle", message: "notificationDocumentActiveSwitchedMessage" },
};

export function AppShell({ children, title }: { children: React.ReactNode; title: string }) {
  const { apiFetch, can, logout, userDisplayName } = useAuth();
  const [languageMenuOpen, setLanguageMenuOpen] = useState(false);
  const [notificationMenuOpen, setNotificationMenuOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationResponse[]>([]);
  const [notificationUnreadCount, setNotificationUnreadCount] = useState(0);
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationsError, setNotificationsError] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const { locale, format, setLocale, t } = useI18n();
  const languageMenuRef = useRef<HTMLDivElement>(null);
  const notificationMenuRef = useRef<HTMLDivElement>(null);
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
    initializeLocale();
  }, []);

  useEffect(() => {
    let cancelled = false;
    getNotificationUnreadCount(apiFetch).then((result) => {
      if (!cancelled) setNotificationUnreadCount(result.unread_count);
    }).catch(() => {
      if (!cancelled) setNotificationUnreadCount(0);
    });
    return () => { cancelled = true; };
  }, [apiFetch]);

  useEffect(() => {
    function closeOnOutside(event: PointerEvent) {
      if (languageMenuRef.current && !languageMenuRef.current.contains(event.target as Node)) setLanguageMenuOpen(false);
      if (notificationMenuRef.current && !notificationMenuRef.current.contains(event.target as Node)) setNotificationMenuOpen(false);
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setUserMenuOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setLanguageMenuOpen(false);
        setNotificationMenuOpen(false);
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

  async function openNotifications() {
    const nextOpen = !notificationMenuOpen;
    setNotificationMenuOpen(nextOpen);
    if (!nextOpen) return;
    setNotificationsLoading(true);
    setNotificationsError(false);
    try {
      const [items, count] = await Promise.all([listNotifications(apiFetch), getNotificationUnreadCount(apiFetch)]);
      setNotifications(items);
      setNotificationUnreadCount(count.unread_count);
    } catch {
      setNotificationsError(true);
    } finally {
      setNotificationsLoading(false);
    }
  }

  async function markRead(notificationId: string) {
    try {
      const updated = await markNotificationRead(apiFetch, notificationId);
      setNotifications((items) => items.map((item) => item.id === notificationId ? updated : item));
      setNotificationUnreadCount((count) => Math.max(0, count - 1));
    } catch {
      setNotificationsError(true);
    }
  }

  async function markAllRead() {
    try {
      await markAllNotificationsRead(apiFetch);
      setNotifications((items) => items.map((item) => ({ ...item, is_read: true })));
      setNotificationUnreadCount(0);
    } catch {
      setNotificationsError(true);
    }
  }

  async function resolveItem(notificationId: string) {
    try {
      const updated = await resolveNotification(apiFetch, notificationId);
      setNotifications((items) => items.map((item) => item.id === notificationId ? updated : item));
      setNotificationUnreadCount((count) => Math.max(0, count - 1));
    } catch {
      setNotificationsError(true);
    }
  }

  function notificationHref(notification: NotificationResponse) {
    const payload = notification.action_payload;
    if (typeof payload.path === "string") return payload.path;
    if (notification.action_type === "review" && typeof payload.approval_task_id === "string") return `/approve/${payload.approval_task_id}`;
    if (notification.project_id) return `/project/${notification.project_id}/import`;
    return "/";
  }

  function notificationCopy(notification: NotificationResponse) {
    const keys = notificationCopyKeys[notification.notification_type];
    if (!keys) return { title: t("notificationGenericTitle"), message: t("notificationGenericMessage") };
    const versionId = typeof notification.action_payload.document_version_id === "string" ? notification.action_payload.document_version_id : "—";
    return { title: t(keys.title), message: format(keys.message, { version: versionId.slice(0, 8) }) };
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
          <div className="notification-menu user-menu" ref={notificationMenuRef}>
            <button aria-expanded={notificationMenuOpen} aria-haspopup="menu" className="icon-button notification-trigger" aria-label={t("notifications")} onClick={openNotifications} type="button">
              <Bell size={18} />
              {notificationUnreadCount > 0 ? <span className="notification-badge">{notificationUnreadCount > 99 ? "99+" : notificationUnreadCount}</span> : null}
            </button>
            {notificationMenuOpen ? (
              <div className="user-menu-panel notification-panel" role="menu">
                <div className="notification-panel-header">
                  <div>
                    <strong>{t("notificationCenter")}</strong>
                    <small>{notificationUnreadCount > 0 ? `${notificationUnreadCount} ${t("notificationUnread")}` : t("notificationAllRead")}</small>
                  </div>
                  <button disabled={!notificationUnreadCount} onClick={markAllRead} type="button">{t("notificationMarkAllRead")}</button>
                </div>
                {notificationsLoading ? <p className="notification-state">{t("notificationLoading")}</p> : null}
                {notificationsError ? <p className="notification-state error">{t("notificationError")}</p> : null}
                {!notificationsLoading && !notificationsError && notifications.length === 0 ? <p className="notification-state">{t("notificationEmpty")}</p> : null}
                <div className="notification-list">
                  {notifications.map((notification) => {
                    const copy = notificationCopy(notification);
                    return <article className={`notification-row severity-${notification.severity}${notification.is_read ? " read" : " unread"}`} key={notification.id} role="menuitem">
                      <div>
                        <strong>{copy.title}</strong>
                        <p>{copy.message}</p>
                        <small>{new Date(notification.created_at).toLocaleString(locale)}</small>
                      </div>
                      <div className="notification-actions">
                        <Link href={notificationHref(notification)} onClick={() => setNotificationMenuOpen(false)} title={t("notificationOpen")}>
                          <ExternalLink size={14} />
                        </Link>
                        {!notification.is_read ? <button onClick={() => markRead(notification.id)} type="button">{t("notificationMarkRead")}</button> : null}
                        {!notification.resolved_at ? <button onClick={() => resolveItem(notification.id)} type="button">{t("notificationResolve")}</button> : null}
                      </div>
                    </article>;
                  })}
                </div>
              </div>
            ) : null}
          </div>
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
    <section className="empty-state forbidden-state" role="status">
      <ShieldCheck size={30} />
      <h2>{title ?? t("forbiddenTitle")}</h2>
      <p>{description ?? t("forbiddenDescription")}</p>
    </section>
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
  return <span className={`status-badge status-${status}`}>{labels[status] ?? status.replaceAll("_", " ")}</span>;
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
