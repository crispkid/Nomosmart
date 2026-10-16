"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { X } from "lucide-react";
import { FeedbackMessage } from "./FeedbackMessage";
import { createFeedbackStore, feedbackSettings, registerFeedbackFailures, type FeedbackMessage as Message, type FeedbackRecord } from "@/lib/feedback";
import { runtimeConfig } from "@/lib/runtimeConfig";
import { useI18n } from "@/lib/i18nClient";
import type { CurrentUser } from "@/lib/api";

type Context = { recent: FeedbackRecord[]; notify: (message: Message, toast?: boolean) => void; dismiss: (id: string, scope: string) => void };
const FeedbackContext = createContext<Context | null>(null);

function subscribeDialogs(listener: () => void) {
  const observer = new MutationObserver(listener);
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-modal"] });
  return () => observer.disconnect();
}
const hasDialog = () => Boolean(document.querySelector('[aria-modal="true"]'));

export function FeedbackProvider({ children, currentUser, enabled }: { children: ReactNode; currentUser: CurrentUser | null; enabled: boolean }) {
  // Permission changes invalidate messages immediately, before effects or a new request.
  const epoch = currentUser && enabled ? JSON.stringify([currentUser.user_id,
    [...currentUser.visible_project_ids].sort(), currentUser.permissions]) : "";
  return <SessionFeedback epoch={epoch}>{children}</SessionFeedback>;
}

function SessionFeedback({ children, epoch }: { children: ReactNode; epoch: string }) {
  const { format, t } = useI18n();
  const settings = useMemo(() => feedbackSettings(runtimeConfig()), []);
  const store = useMemo(() => createFeedbackStore(settings, Boolean(epoch)), [settings, epoch]);
  const { recent, queue } = useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
  const dialogOpen = useSyncExternalStore(subscribeDialogs, hasDialog, () => false);
  useEffect(() => { store.activate(); return () => store.dispose(); }, [store]);
  useEffect(() => registerFeedbackFailures(message => store.notify(message, false)), [store]);
  const value = useMemo(() => ({ recent, notify: store.notify, dismiss: store.dismiss }), [recent, store]);
  return <FeedbackContext.Provider value={value}>{children}
    <aside hidden={dialogOpen} className="feedback-toast-viewport" aria-label={t("feedbackResults")}>
      {queue.slice(0, settings.toastVisibleLimit).map(item => <FeedbackToast key={JSON.stringify([epoch, item.scope, item.id])} paused={dialogOpen} duration={settings.toastDurationMs} onDismiss={() => store.dismiss(item.id, item.scope)}>
        <FeedbackMessage tone={item.tone} critical={item.critical} title={format(item.title, item.params ?? {})}>
          {item.reason ? format(item.reason, item.params ?? {}) : null}
        </FeedbackMessage>
      </FeedbackToast>)}
    </aside>
  </FeedbackContext.Provider>;
}

export function FeedbackToast({ children, duration, onDismiss, paused = false }: { children: ReactNode; duration: number; onDismiss: () => void; paused?: boolean }) {
  const { t } = useI18n();
  const [hovered, setHovered] = useState(false), [focused, setFocused] = useState(false);
  const [hidden, setHidden] = useState(true);
  const remaining = useRef(duration);
  const dismissRef = useRef(onDismiss);
  useEffect(() => { dismissRef.current = onDismiss; }, [onDismiss]);
  useEffect(() => {
    const update = () => setHidden(document.visibilityState !== "visible");
    update(); document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (hovered || focused || hidden || paused) return;
    const started = performance.now();
    const timer = window.setTimeout(() => dismissRef.current(), remaining.current);
    return () => { window.clearTimeout(timer); remaining.current = Math.max(0, remaining.current - (performance.now() - started)); };
  }, [hovered, focused, hidden, paused]);
  return <div className="feedback-toast" onPointerEnter={() => setHovered(true)} onPointerLeave={() => setHovered(false)} onFocusCapture={() => setFocused(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false); }}>
    {children}<button className="feedback-dismiss" type="button" aria-label={t("close")} onClick={onDismiss}><X size={18} /></button>
  </div>;
}

export function useFeedback() {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error("feedback_provider_required");
  return context;
}
