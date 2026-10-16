"use client";

import Link from "next/link";
import { Bell, CheckCheck, ExternalLink, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "./AuthProvider";
import { useFeedback } from "./FeedbackProvider";
import { FeedbackMessage, feedbackIcons } from "./FeedbackMessage";
import { getNotificationUnreadCount, listNotificationPage, markAllNotificationsRead, markNotificationRead, resolveNotification, type NotificationResponse } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

const copies: Record<string, [TranslationKey, TranslationKey]> = {
  "review.manager.pending": ["notificationReviewManagerPendingTitle", "notificationReviewManagerPendingMessage"],
  "review.owner.pending": ["notificationReviewOwnerPendingTitle", "notificationReviewOwnerPendingMessage"],
  "review.approved": ["notificationReviewApprovedTitle", "notificationReviewApprovedMessage"],
  "review.rejected": ["notificationReviewRejectedTitle", "notificationReviewRejectedMessage"],
  "document.published": ["notificationDocumentPublishedTitle", "notificationDocumentPublishedMessage"],
  "document.active_switched": ["notificationDocumentActiveSwitchedTitle", "notificationDocumentActiveSwitchedMessage"],
  reference_source_event: ["notificationReferenceTitle", "notificationReferenceMessage"],
  "graph_sync.failed": ["notificationGraphTitle", "notificationGraphMessage"],
};

function destination(item: NotificationResponse): string {
  // Never execute a server-supplied URL, protocol, or arbitrary navigation path.
  const task = item.action_payload.approval_task_id;
  if (item.action_type === "review" && typeof task === "string" && /^[0-9a-f-]{36}$/i.test(task)) return `/approve/${task}`;
  return item.project_id && /^[0-9a-f-]{36}$/i.test(item.project_id) ? `/project/${item.project_id}/import` : "/";
}

export function NotificationCenter() {
  const { currentUser } = useAuth();
  const scope = JSON.stringify([currentUser?.user_id, currentUser?.visible_project_ids, currentUser?.permissions]);
  return <ScopedNotificationCenter key={scope} />;
}

function ScopedNotificationCenter() {
  const { apiFetch } = useAuth();
  const { recent, notify } = useFeedback();
  const { t, format, locale } = useI18n();
  const [open, setOpen] = useState(false), [tab, setTab] = useState<"pending" | "all" | "recent">("pending");
  const [items, setItems] = useState<NotificationResponse[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null), [loading, setLoading] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0), panel = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const refreshCount = useCallback(async () => {
    const request = generation.current;
    try { const result = await getNotificationUnreadCount(apiFetch); if (request === generation.current) setCount(result.unread_count); }
    catch { if (request === generation.current) setCount(null); }
  }, [apiFetch]);
  useEffect(() => { let active = true; getNotificationUnreadCount(apiFetch).then(result => { if (active) setCount(result.unread_count); }).catch(() => { if (active) setCount(null); }); return () => { active = false; }; }, [apiFetch]);
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (panel.current && !panel.current.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape" && open) { setOpen(false); trigger.current?.focus(); } };
    window.addEventListener("pointerdown", outside); window.addEventListener("keydown", escape);
    return () => { window.removeEventListener("pointerdown", outside); window.removeEventListener("keydown", escape); };
  }, [open]);

  async function load(selected: "pending" | "all", append = false, defaultTab = false) {
    const request = ++generation.current;
    setLoading(true); setError("");
    if (!append) { setItems([]); setCursor(null); }
    try {
      let page = await listNotificationPage(apiFetch, { ...(selected === "pending" ? { resolved: false } : {}), ...(append && cursor ? { cursor } : {}) });
      if (request !== generation.current) return;
      if (defaultTab && page.items.length === 0 && !page.has_more) {
        selected = "all"; page = await listNotificationPage(apiFetch);
        if (request !== generation.current) return;
      }
      setTab(selected);
      setItems(previous => append ? [...previous, ...page.items.filter(item => !previous.some(old => old.id === item.id))] : page.items);
      setCursor(page.has_more ? page.next_cursor : null);
      await refreshCount();
    } catch (caught) { if (request === generation.current) setError(operationalErrorMessage(caught, t, format)); }
    finally { if (request === generation.current) setLoading(false); }
  }

  async function command(item: NotificationResponse | null, resolve = false) {
    if (busy) return;
    const request = generation.current;
    setBusy(true); setError("");
    try {
      if (!item) { await markAllNotificationsRead(apiFetch); if (request === generation.current) setItems(old => old.map(value => ({ ...value, is_read: true }))); }
      else {
        const updated = await (resolve ? resolveNotification : markNotificationRead)(apiFetch, item.id);
        if (resolve && updated.resolved_at) notify({ id: `notification:${updated.id}:${updated.resolved_at}`, scope: "notifications", tone: "success", title: "notificationResolved" });
        if (request === generation.current) setItems(old => old.map(value => value.id === item.id ? updated : value).filter(value => tab !== "pending" || !value.resolved_at));
      }
      if (request === generation.current) await refreshCount();
    } catch (caught) { if (request === generation.current) setError(operationalErrorMessage(caught, t, format)); }
    finally { setBusy(false); }
  }

  return <div className="notification-menu user-menu" ref={panel}>
    <button ref={trigger} className="icon-button notification-trigger" type="button" aria-label={t("notificationCenter")} aria-expanded={open} aria-controls="feedback-notification-center" onClick={() => { setOpen(!open); if (!open) void load("pending", false, true); }}>
      <Bell size={20} />{count !== null && count > 0 ? <span className="notification-badge">{count > 99 ? "99+" : count}</span> : null}
    </button>
    {open ? <section id="feedback-notification-center" className="feedback-notification-panel" aria-label={t("notificationCenter")}>
      <header><div><strong>{t("notificationCenter")}</strong><small>{count === null ? t("notificationCountUnknown") : count === 0 ? t("notificationAllRead") : format("notificationUnreadCount", { count: count.toLocaleString(locale) })}</small></div><button type="button" className="icon-button" aria-label={t("close")} onClick={() => { setOpen(false); trigger.current?.focus(); }}><X size={18} /></button></header>
      <div className="feedback-notification-tabs" role="tablist" aria-label={t("notificationCenter")}>
        {(["pending", "all", "recent"] as const).map(value => <button key={value} id={`feedback-tab-${value}`} role="tab" aria-selected={value === tab} aria-controls="feedback-notification-items" type="button" disabled={busy} onClick={() => { setTab(value); if (value === "recent") { generation.current++; setLoading(false); setError(""); } else void load(value); }}>{t(value === "pending" ? "notificationPending" : value === "all" ? "notificationAll" : "notificationRecent")}</button>)}
      </div>
      {error ? <FeedbackMessage actions={<button type="button" className="text-link" disabled={busy || loading || tab === "recent"} onClick={() => { if (tab !== "recent") void load(tab); }}>{t("retry")}</button>}>{error}</FeedbackMessage> : null}
      {tab !== "recent" ? <button className="feedback-notification-readall" disabled={busy || loading || count === null || count === 0} onClick={() => void command(null)} type="button"><CheckCheck size={15} />{t("notificationMarkAllRead")}</button> : null}
      <div id="feedback-notification-items" role="tabpanel" aria-labelledby={`feedback-tab-${tab}`} className="feedback-notification-list" aria-busy={loading}>
        {loading ? <p className="notification-state" role="status"><Loader2 size={16} className="spin" />{t("notificationLoading")}</p> : null}
        {tab === "recent" ? recent.map(item => <article className="feedback-notification-row" key={JSON.stringify([item.scope, item.id])}><FeedbackMessage announce={false} tone={item.tone} title={format(item.title, item.params ?? {})}>{item.reason ? format(item.reason, item.params ?? {}) : null}</FeedbackMessage><time>{new Date(item.createdAt).toLocaleString(locale)}</time></article>) : items.map(item => {
          const keys = copies[item.notification_type], tone = item.severity === "critical" || item.severity === "error" ? "error" : item.severity === "warning" ? "warning" : "info", Icon = feedbackIcons[tone];
          const version = typeof item.action_payload.document_version_id === "string" && /^[0-9a-f-]{36}$/i.test(item.action_payload.document_version_id) ? item.action_payload.document_version_id.slice(0, 8) : "—";
          return <article data-notification-id={item.id} className={`feedback-notification-row feedback-${tone}${item.is_read ? "" : " unread"}`} key={item.id}>
            <Icon size={19} aria-hidden="true" /><div className="feedback-notification-copy"><strong>{item.severity === "critical" ? `${t("feedbackCritical")} · ` : ""}{keys ? t(keys[0]) : t("notificationGenericTitle")}</strong><p>{keys ? format(keys[1], { version }) : t("notificationGenericMessage")}</p>
              <div className="feedback-notification-meta"><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time><span>{t(item.is_read ? "notificationRead" : "notificationUnreadState")}</span><span>{t(item.resolved_at ? "notificationResolved" : "notificationPending")}</span></div>
              <div className="feedback-notification-actions"><Link href={destination(item)} onClick={() => setOpen(false)}><ExternalLink size={14} />{t("notificationOpen")}</Link>{!item.is_read ? <button disabled={busy} type="button" onClick={() => void command(item)}>{t("notificationMarkRead")}</button> : null}{!item.resolved_at && item.can_resolve_manual === true ? <button disabled={busy} type="button" onClick={() => void command(item, true)}>{t("notificationResolve")}</button> : null}</div>
              {!item.resolved_at && item.can_resolve_manual !== true ? <small>{t("notificationBusinessActionRequired")}</small> : null}
            </div>
          </article>;
        })}
        {!loading && !error && (tab === "recent" ? recent.length === 0 : items.length === 0) ? <p className="notification-state">{t("notificationEmpty")}</p> : null}
        {tab !== "recent" && cursor ? <button disabled={loading || busy} className="action-button secondary" type="button" onClick={() => void load(tab, true)}>{t("notificationLoadMore")}</button> : null}
      </div>
    </section> : null}
  </div>;
}
