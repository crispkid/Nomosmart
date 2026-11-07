"use client";

import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { BrowserTitle } from "@/lib/browserTitle";
import { transportFetch } from "@/lib/transportError";
import { FeedbackProvider } from "./FeedbackProvider";
import { GraphLayoutSession } from "./GraphLayoutSession";
import { clearGraphLayoutSession } from "@/lib/graphLayoutCache";
import { createOperationGuardRegistry, type OperationGuardRegistry } from "@/lib/operationGuard";
import { ApplicationAccessDenied } from "./ApplicationAccessDenied";
import { AuthConnectionRecovery } from "./AuthConnectionRecovery";
import { apiJson, can, canAnyView, discardSessionDraft, getCurrentUser, restoreSessionDraft, type CurrentUser, type PermissionAction } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { apiBaseUrl, safeReturnPath } from "@/lib/oidc";
import { captureSessionDraft, randomDraftNonce } from "@/lib/sessionDrafts";
import { formatPersonName } from "@/lib/personName";
import { isProtectedApplicationPage } from "@/lib/applicationRoutes";

type SessionState = { authenticated: boolean; csrf_token: string | null; idle_expires_at: string | null };
type DraftPointer = { draftId: string; nonce: string; returnPath: string };
type AuthValue = {
  /** @deprecated Token installation is retired; callers must sign in through the server. */
  tokens: null;
  installTokens: (_retired: unknown) => never;
  currentUser: CurrentUser | null;
  applicationAccess: "checking" | "granted" | "denied";
  authReady: boolean;
  authError: string | null;
  userDisplayName: string;
  apiFetch: (input: string, init?: RequestInit) => Promise<Response>;
  logout: () => Promise<void>;
  can: (moduleName: string, functionName: string, action: PermissionAction) => boolean;
  canViewModule: (moduleName: string) => boolean;
  operationGuards: OperationGuardRegistry;
};
const AuthContext = createContext<AuthValue | null>(null);
function rejectRetiredTokens(_retired: unknown): never { throw new Error("auth_contract_changed: use server sign-in"); }
const draftStorage = "nomosmart-session-draft-pointer";

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { locale, t } = useI18n();
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [applicationAccess, setApplicationAccess] = useState<AuthValue["applicationAccess"]>("checking");
  const [authReady, setAuthReady] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [deadline, setDeadline] = useState<string | null>(null);
  const [connectionFailed, setConnectionFailed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [recheckResult, setRecheckResult] = useState<"idle" | "denied" | "failed">("idle");
  const [restorePrompt, setRestorePrompt] = useState<DraftPointer | null>(null);
  const csrf = useRef<string | null>(null);
  const closing = useRef(false);
  const generation = useRef(0);
  const channel = useRef<BroadcastChannel | null>(null);
  const hasDeadline = Boolean(deadline);
  const isProtected = isProtectedApplicationPage(pathname);
  const identity = JSON.stringify([currentUser?.user_id, currentUser?.permissions, applicationAccess]);
  const operationGuards = useMemo(() => createOperationGuardRegistry(identity), [identity]);
  useLayoutEffect(() => () => operationGuards.clear(), [operationGuards]);

  const login = useCallback((notice: string) => {
    if (closing.current) return;
    closing.current = true;
    generation.current += 1;
    clearGraphLayoutSession();
    const path = safeReturnPath(`${window.location.pathname}${window.location.search}`);
    const target = new URL("/login", window.location.origin);
    target.searchParams.set("notice", notice);
    target.searchParams.set("returnTo", path);
    window.location.replace(target.pathname + target.search);
  }, []);

  const apiFetch = useCallback(async (input: string, init: RequestInit = {}) => {
    if (closing.current) throw new DOMException("Session closed", "AbortError");
    const epoch = generation.current;
    const headers = new Headers(init.headers);
    const mutation = !["GET", "HEAD", "OPTIONS"].includes((init.method ?? "GET").toUpperCase());
    const endpoint = new URL(input, window.location.origin);
    const base = new URL(apiBaseUrl(), window.location.origin);
    if (endpoint.origin !== base.origin || !endpoint.pathname.startsWith(base.pathname + "/")) throw new Error("Unexpected API destination");
    if (mutation && csrf.current) headers.set("X-CSRF-Token", csrf.current);
    const response = await transportFetch(input, { ...init, headers, credentials: "same-origin", cache: "no-store" });
    if (closing.current || epoch !== generation.current) throw new DOMException("Session changed", "AbortError");
    if (response.status === 401) {
      const body = await response.clone().json().catch(() => ({}));
      if (["authentication_required", "session_expired", "session_revoked"].includes(body.code)) login("session_expired");
    }
    if (response.status === 403) {
      const body = await response.clone().json().catch(() => ({}));
      if (body.code === "application_access_denied") { setApplicationAccess("denied"); setCurrentUser(null); }
      else if (["user_disabled", "user_not_synchronized"].includes(body.code)) login("account_unavailable");
    }
    return response;
  }, [login]);

  const probe = useCallback(async () => {
    if (closing.current) return;
    setChecking(true);
    try {
      const stateResponse = await transportFetch(`${apiBaseUrl()}/auth/session`, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (!stateResponse.ok) throw new Error("session_probe_failed");
      const state = await stateResponse.json() as SessionState;
      if (closing.current) return;
      csrf.current = state.csrf_token;
      setDeadline(state.authenticated ? state.idle_expires_at : null);
      if (!state.authenticated) {
        setCurrentUser(null); setApplicationAccess("checking"); setAuthReady(true); setConnectionFailed(false);
        if (isProtectedApplicationPage(window.location.pathname)) login("session_expired");
        return;
      }
      const response = await apiFetch(`${apiBaseUrl()}/auth/me`);
      if (closing.current) return;
      if (response.status === 403) { setApplicationAccess("denied"); setRecheckResult("denied"); }
      else if (response.ok) {
        const user = await response.json() as CurrentUser;
        setCurrentUser(user); setApplicationAccess("granted"); setRecheckResult("idle");
        csrf.current = user.csrf_token ?? state.csrf_token;
        setDeadline(user.idle_expires_at ?? state.idle_expires_at);
      } else throw new Error("session_profile_failed");
      setAuthReady(true); setConnectionFailed(false); setAuthError(null);
    } catch {
      if (!closing.current) { setConnectionFailed(true); setRecheckResult("failed"); setAuthError(t("authLoadFailed")); }
    } finally { setChecking(false); }
  }, [apiFetch, login, t]);

  useEffect(() => { (window as Window & { __NOMOSMART_AUTH_HYDRATED__?: boolean }).__NOMOSMART_AUTH_HYDRATED__ = true; }, []);
  useEffect(() => { const timer = window.setTimeout(() => { void probe(); }, 0); return () => window.clearTimeout(timer); }, [probe]);
  useEffect(() => {
    const broadcast = new BroadcastChannel("nomosmart-session-v2");
    channel.current = broadcast;
    broadcast.onmessage = event => {
      if (event.data?.type === "logout") login("logged_out");
      else if (event.data?.type === "activity" && typeof event.data.deadline === "string" && Number.isFinite(Date.parse(event.data.deadline))) setDeadline(event.data.deadline);
    };
    return () => { channel.current = null; broadcast.close(); };
  }, [login]);

  useEffect(() => {
    if (!deadline || !authReady) return;
    // A deadline check is read-only. It never extends the shared session.
    const timer = window.setTimeout(() => { void probe(); }, Math.max(50, Date.parse(deadline) - Date.now() + 100));
    return () => window.clearTimeout(timer);
  }, [authReady, deadline, probe]);

  useEffect(() => {
    if (!authReady || !hasDeadline || closing.current) return;
    let lastSent = 0, pending = false;
    const activity = (event: Event) => {
      if (!event.isTrusted || document.visibilityState !== "visible" || pending || Date.now() - lastSent < 15000 || closing.current) return;
      pending = true; lastSent = Date.now();
      void apiFetch(`${apiBaseUrl()}/auth/activity`, { method: "POST" }).then(async response => {
        if (!response.ok) return;
        const result = await response.json() as { idle_expires_at: string };
        setDeadline(result.idle_expires_at);
        channel.current?.postMessage({ type: "activity", deadline: result.idle_expires_at });
      }).catch(() => { /* Retry only on the next genuine user action. */ }).finally(() => { pending = false; });
    };
    const events = ["pointerdown", "keydown", "touchstart", "scroll"];
    events.forEach(name => window.addEventListener(name, activity, { passive: true }));
    return () => events.forEach(name => window.removeEventListener(name, activity));
  }, [apiFetch, authReady, hasDeadline]);

  useEffect(() => {
    if (!deadline || !currentUser || !isProtected) return;
    const timer = window.setTimeout(() => {
      const captured = captureSessionDraft();
      if (!captured || closing.current) return;
      const nonce = randomDraftNonce(), returnPath = safeReturnPath(window.location.pathname + window.location.search);
      void apiJson<{ draft_id: string }>(apiFetch, "/auth/session-drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ form_key: captured.formKey, return_path: returnPath, nonce, payload: captured.payload }) }).then(created => {
        sessionStorage.setItem(draftStorage, JSON.stringify({ draftId: created.draft_id, nonce, returnPath }));
      }).catch(() => undefined);
    }, Math.max(0, Date.parse(deadline) - Date.now() - 10000));
    return () => window.clearTimeout(timer);
  }, [apiFetch, currentUser, deadline, isProtected]);

  useEffect(() => {
    if (!currentUser || !isProtected) return;
    try {
      const pointer = JSON.parse(sessionStorage.getItem(draftStorage) || "null") as DraftPointer | null;
      if (pointer && pointer.returnPath === window.location.pathname + window.location.search) {
        const timer = window.setTimeout(() => setRestorePrompt(pointer), 0);
        return () => window.clearTimeout(timer);
      }
    } catch { sessionStorage.removeItem(draftStorage); }
  }, [currentUser, isProtected, pathname]);

  const finishDraft = useCallback(async (restore: boolean) => {
    if (!restorePrompt) return;
    if (restore) {
      const saved = await restoreSessionDraft(apiFetch, restorePrompt.draftId, { return_path: restorePrompt.returnPath, nonce: restorePrompt.nonce });
      window.dispatchEvent(new CustomEvent("nomosmart:restore-session-draft", { detail: { formKey: saved.form_key, payload: saved.payload } }));
    } else await discardSessionDraft(apiFetch, restorePrompt.draftId, { return_path: restorePrompt.returnPath, nonce: restorePrompt.nonce });
    sessionStorage.removeItem(draftStorage); setRestorePrompt(null);
  }, [apiFetch, restorePrompt]);

  const logout = useCallback(async () => {
    if (closing.current) return;
    closing.current = true;
    generation.current += 1;
    operationGuards.clear(); clearGraphLayoutSession();
    setCurrentUser(null); setApplicationAccess("checking"); setAuthReady(false);
    try {
      const response = await transportFetch(`${apiBaseUrl()}/auth/logout`, { method: "POST", headers: { "X-CSRF-Token": csrf.current || "" }, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error("logout_failed");
    } catch {
      window.location.replace("/login?notice=logout_incomplete");
      return;
    }
    sessionStorage.removeItem(draftStorage);
    channel.current?.postMessage({ type: "logout" });
    window.location.replace("/login?notice=logged_out");
  }, [operationGuards]);

  const userDisplayName = currentUser ? formatPersonName(currentUser, locale) || "NomoSmart" : "NomoSmart";
  const hasPermission = useCallback((module: string, fn: string, action: PermissionAction) => can(currentUser?.permissions ?? [], module, fn, action), [currentUser]);
  const canViewModule = useCallback((module: string) => canAnyView(currentUser?.permissions ?? [], module), [currentUser]);
  const value = useMemo(() => ({ tokens: null, installTokens: rejectRetiredTokens, currentUser, applicationAccess, authReady, authError, userDisplayName, apiFetch, logout, can: hasPermission, canViewModule, operationGuards }), [currentUser, applicationAccess, authReady, authError, userDisplayName, apiFetch, logout, hasPermission, canViewModule, operationGuards]);
  const ready = authReady && currentUser && applicationAccess === "granted";
  return <AuthContext.Provider value={value}><GraphLayoutSession identity={ready ? identity : null}><FeedbackProvider currentUser={currentUser} enabled={Boolean(ready)}>
    {!isProtected ? children : connectionFailed ? <AuthConnectionRecovery busy={checking} failed onRetry={() => { void probe(); }} /> : applicationAccess === "denied" ? <ApplicationAccessDenied onLogout={logout} onRecheck={probe} recheckResult={recheckResult} rechecking={checking} userDisplayName={userDisplayName} /> : ready ? children : <><BrowserTitle label={t("authCheckingSession")} /><main className="auth-loading" role={authError ? "alert" : "status"}>{authError || t("authCheckingSession")}</main></>}
    {restorePrompt ? <div className="auth-session-modal" role="dialog" aria-modal="true" aria-labelledby="draft-restore-title"><section><h2 id="draft-restore-title">{t("restoreDraftTitle")}</h2><p>{t("restoreDraftHelp")}</p><footer><button className="action-button secondary" onClick={() => { void finishDraft(false); }} type="button">{t("discardDraft")}</button><button className="action-button" onClick={() => { void finishDraft(true); }} type="button">{t("restoreDraft")}</button></footer></section></div> : null}
  </FeedbackProvider></GraphLayoutSession></AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error("useAuth must be used inside AuthProvider"); return value; }
