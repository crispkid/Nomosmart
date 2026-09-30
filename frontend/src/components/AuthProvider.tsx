"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApplicationAccessDenied } from "@/components/ApplicationAccessDenied";
import { AuthConnectionRecovery } from "@/components/AuthConnectionRecovery";
import { can, canAnyView, discardSessionDraft, getCurrentUser, restoreSessionDraft, type ApiError, type CurrentUser, type PermissionAction } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { apiBaseUrl, decodeJwtPayload, oidcConfig, safeReturnPath, type OidcTokens } from "@/lib/oidc";
import { captureSessionDraft, randomDraftNonce } from "@/lib/sessionDrafts";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";
import { AuthSessionLifecycle, authLogoutTimeout, RefreshFailure } from "@/lib/authSessionLifecycle";
import { AuthRecoveryProbe } from "@/lib/authRecovery";
import { runtimeConfig } from "@/lib/runtimeConfig";
import { isProtectedApplicationPage } from "@/lib/applicationRoutes";

type AuthValue = {
  tokens: OidcTokens | null;
  currentUser: CurrentUser | null;
  applicationAccess: "checking" | "granted" | "denied";
  authReady: boolean;
  authError: string | null;
  userDisplayName: string;
  installTokens: (tokens: OidcTokens) => boolean;
  apiFetch: (input: string, init?: RequestInit) => Promise<Response>;
  logout: () => Promise<void>;
  can: (moduleName: string, functionName: string, action: PermissionAction) => boolean;
  canViewModule: (moduleName: string) => boolean;
};
const AuthContext = createContext<AuthValue | null>(null);
const unavailableAccountCodes = new Set(["user_disabled", "user_not_synchronized"]);

async function responseErrorCode(response: Response): Promise<string | null> {
  const body = await response.clone().json().catch(() => ({})) as { code?: string };
  return typeof body.code === "string" ? body.code : null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { locale, format, localize, t } = useI18n();
  const [tokens, setTokens] = useState<OidcTokens | null>(null);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [applicationAccess, setApplicationAccess] = useState<"checking" | "granted" | "denied">("checking");
  const [accessRechecking, setAccessRechecking] = useState(false);
  const [accessRecheckResult, setAccessRecheckResult] = useState<"idle" | "denied" | "failed">("idle");
  const [authReady, setAuthReady] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [restorePrompt, setRestorePrompt] = useState<{ draftId: string; nonce: string; returnPath: string } | null>(null);
  const [lifecycle] = useState(() => new AuthSessionLifecycle());
  const logoutPromise = useRef<Promise<void> | null>(null);
  const recheckPromise = useRef<Promise<void> | null>(null);
  const applicationAccessRef = useRef<"checking" | "granted" | "denied">("checking");
  const deniedReturnPath = useRef("/");
  const authRedirecting = useRef(false);
  const sessionRecoveryStarted = useRef(false);
  const recoveryProbe = useRef<AuthRecoveryProbe | null>(null);
  const recoveryReturnPath = useRef("/");
  const [connectionRecovery, setConnectionRecovery] = useState<"idle" | "waiting" | "checking" | "failed">("idle");
  const protectedPath = isProtectedApplicationPage(pathname);
  const routeBypassesAuth = !protectedPath;

  useEffect(() => {
    (window as Window & { __NOMOSMART_AUTH_HYDRATED__?: boolean }).__NOMOSMART_AUTH_HYDRATED__ = true;
  }, []);

  useEffect(() => {
    if (protectedPath && !tokens && !authRedirecting.current && connectionRecovery === "idle") {
      authRedirecting.current = true;
      window.location.replace(`/api/auth/start?prompt=none&returnTo=${encodeURIComponent(`${pathname}${window.location.search}`)}`);
    }
  }, [connectionRecovery, pathname, protectedPath, tokens]);

  const retryConnection = useCallback((automatic = false) => {
    const probe = recoveryProbe.current;
    const work = probe?.start(automatic, `${apiBaseUrl()}/health`, authLogoutTimeout(runtimeConfig().authLogoutTimeoutMs));
    if (!work) return;
    setConnectionRecovery("checking");
    void work.then((connected) => {
      if (recoveryProbe.current !== probe) return;
      if (!connected) { setConnectionRecovery("failed"); return; }
      // Never replay an uncertain rotated refresh token or the interrupted POST.
      recoveryProbe.current = null;
      probe?.stop();
      if (!isProtectedApplicationPage(window.location.pathname)) return;
      window.location.replace(`/api/auth/start?prompt=none&returnTo=${encodeURIComponent(recoveryReturnPath.current)}`);
    });
  }, []);

  useEffect(() => {
    if (connectionRecovery === "idle" || !protectedPath) return;
    const online = () => retryConnection(true);
    window.addEventListener("online", online);
    if (navigator.onLine) online();
    return () => window.removeEventListener("online", online);
  }, [connectionRecovery, protectedPath, retryConnection]);

  useEffect(() => () => { recoveryProbe.current?.stop(); recoveryProbe.current = null; }, []);

  const waitForConnection = useCallback(() => {
    if (sessionRecoveryStarted.current) return;
    sessionRecoveryStarted.current = true;
    authRedirecting.current = true;
    recoveryReturnPath.current = safeReturnPath(`${window.location.pathname}${window.location.search}`);
    lifecycle.invalidate();
    applicationAccessRef.current = "checking";
    setCurrentUser(null); setTokens(null); setApplicationAccess("checking");
    setAuthReady(false); setAuthError(null); setRestorePrompt(null);
    recoveryProbe.current = new AuthRecoveryProbe();
    setConnectionRecovery("waiting");
  }, [lifecycle]);

  const refresh = useCallback(async (generation: number, rejectedToken?: string) => {
    const next = await lifecycle.refresh(generation, "/api/auth/refresh", authLogoutTimeout(runtimeConfig().authLogoutTimeoutMs), rejectedToken);
    lifecycle.assertActive(generation);
    setTokens(next);
    return next;
  }, [lifecycle]);

  const redirectAccountUnavailable = useCallback(() => {
    if (authRedirecting.current) return;
    authRedirecting.current = true;
    lifecycle.invalidate();
    applicationAccessRef.current = "checking";
    setCurrentUser(null);
    setTokens(null);
    window.location.replace("/api/auth/login-recovery?mode=account_unavailable");
  }, [lifecycle]);

  const expireSession = useCallback(() => {
    if (sessionRecoveryStarted.current) return;
    sessionRecoveryStarted.current = true;
    authRedirecting.current = true;
    const returnPath = safeReturnPath(`${window.location.pathname}${window.location.search}`);
    const draftToken = lifecycle.current()?.accessToken;
    lifecycle.invalidate();
    const generation = lifecycle.generation();
    applicationAccessRef.current = "checking";
    setCurrentUser(null);
    setTokens(null);
    void (async () => {
      let nextReturnPath = returnPath;
      if (draftToken) {
        const captured = captureSessionDraft();
        if (captured) {
          const nonce = randomDraftNonce();
          try {
            const response = await fetch(`${apiBaseUrl()}/auth/session-drafts`, { method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${draftToken}` }, body: JSON.stringify({ form_key: captured.formKey, return_path: returnPath, nonce, payload: captured.payload }), cache: "no-store", signal: AbortSignal.timeout(1500) });
            if (!response.ok) throw new Error("draft_create_failed");
            const created = await response.json() as { draft_id: string };
            const url = new URL(returnPath, window.location.origin);
            url.searchParams.set("reauthDraftId", created.draft_id);
            url.searchParams.set("reauthNonce", nonce);
            nextReturnPath = `${url.pathname}${url.search}`;
          } catch {
            nextReturnPath = returnPath;
          }
        }
      }
      if (lifecycle.generation() === generation) window.location.replace(`/api/auth/login-recovery?mode=session_expired&returnTo=${encodeURIComponent(nextReturnPath)}`);
    })();
  }, [lifecycle]);

  const handleRefreshFailure = useCallback((error: unknown) => {
    if (error instanceof RefreshFailure && error.kind === "unavailable") waitForConnection();
    else expireSession();
  }, [expireSession, waitForConnection]);

  const enterApplicationAccessDenied = useCallback(() => {
    if (lifecycle.isClosing()) return;
    const isFirstTransition = applicationAccessRef.current !== "denied";
    applicationAccessRef.current = "denied";
    const attemptedPath = safeReturnPath(`${window.location.pathname}${window.location.search}`);
    if (isFirstTransition && window.location.pathname !== "/access-denied") deniedReturnPath.current = attemptedPath;
    setCurrentUser(null);
    setApplicationAccess("denied");
    setAuthError(null);
    setAuthReady(true);
    if (isFirstTransition && window.location.pathname !== "/access-denied") router.replace("/access-denied");
  }, [lifecycle, router]);

  const apiFetch = useCallback(async (input: string, init: RequestInit = {}) => {
    const generation = lifecycle.generation();
    lifecycle.assertActive(generation);
    init.signal?.throwIfAborted();
    let current = lifecycle.current();
    if (!current) throw new Error("authentication_required");
    try {
      if (current.expiresAt - Date.now() < 30_000) current = await refresh(generation);
    } catch (error) {
      init.signal?.throwIfAborted();
      lifecycle.assertActive(generation);
      handleRefreshFailure(error);
      throw error;
    }
    const execute = async (accessToken: string) => {
      lifecycle.assertActive(generation);
      // The caller owns this request, not the shared credential refresh.
      init.signal?.throwIfAborted();
      const response = await fetch(input, { ...init, headers: { ...init.headers, Authorization: `Bearer ${accessToken}` } });
      lifecycle.assertActive(generation);
      init.signal?.throwIfAborted();
      return response;
    };
    let response = await execute(current.accessToken);
    if (response.status === 401) {
      let refreshed: OidcTokens;
      try {
        refreshed = await refresh(generation, current.accessToken);
      } catch (error) {
        init.signal?.throwIfAborted();
        lifecycle.assertActive(generation);
        handleRefreshFailure(error);
        throw error;
      }
      // A cancelled or disconnected business retry is not an auth failure.
      response = await execute(refreshed.accessToken);
      if (response.status === 401) expireSession();
    }
    if (response.status === 403) {
      const code = (await responseErrorCode(response)) ?? "";
      lifecycle.assertActive(generation);
      if (unavailableAccountCodes.has(code)) redirectAccountUnavailable();
      else if (code === "application_access_denied") enterApplicationAccessDenied();
    }
    return response;
  }, [enterApplicationAccessDenied, expireSession, handleRefreshFailure, lifecycle, redirectAccountUnavailable, refresh]);

  useEffect(() => {
    let cancelled = false;
    const generation = lifecycle.generation();
    const active = () => !cancelled && lifecycle.accepts(generation);
    if (!tokens) {
      window.setTimeout(() => {
        if (active()) {
          applicationAccessRef.current = "checking";
          setCurrentUser(null);
          setApplicationAccess("checking");
          setAuthReady(routeBypassesAuth);
          setAuthError(null);
        }
      }, 0);
      return () => { cancelled = true; };
    }
    if (routeBypassesAuth) {
      window.setTimeout(() => {
        if (active()) {
          setAuthReady(true);
          setAuthError(null);
        }
      }, 0);
      return () => { cancelled = true; };
    }
    if (applicationAccess === "denied" || (applicationAccess === "granted" && currentUser)) {
      window.setTimeout(() => {
        if (active()) setAuthReady(true);
      }, 0);
      return () => { cancelled = true; };
    }
    window.setTimeout(() => {
      if (!active()) return;
      setApplicationAccess("checking");
      setAuthReady(false);
      setAuthError(null);
      const bootstrapFetch = async (input: string, init: RequestInit = {}) => {
        lifecycle.assertActive(generation);
        const current = lifecycle.current();
        if (!current) throw new Error("authentication_required");
        const execute = async (accessToken: string) => {
          lifecycle.assertActive(generation);
          const result = await fetch(input, { ...init, headers: { ...init.headers, Authorization: `Bearer ${accessToken}` } });
          lifecycle.assertActive(generation);
          return result;
        };
        let response = await execute(current.accessToken);
        if (response.status !== 401) return response;
        let next: OidcTokens;
        try { next = await refresh(generation, current.accessToken); }
        catch (error) { lifecycle.assertActive(generation); handleRefreshFailure(error); throw error; }
        response = await execute(next.accessToken);
        return response;
      };
      getCurrentUser(bootstrapFetch).then((user) => {
        if (active()) {
          applicationAccessRef.current = "granted";
          setCurrentUser(user);
          setApplicationAccess("granted");
          setAuthReady(true);
          if (window.location.pathname === "/access-denied") router.replace("/");
        }
      }).catch((error: ApiError) => {
        if (active()) {
          if (error.status === 401) {
            expireSession();
            return;
          }
          if (error.status === 403 && unavailableAccountCodes.has(error.code)) {
            redirectAccountUnavailable();
            return;
          }
          if (error.status === 403 && error.code === "application_access_denied") {
            enterApplicationAccessDenied();
            return;
          }
          setAuthError(operationalErrorMessage(error, t, format));
          setAuthReady(true);
        }
      });
    }, 0);
    return () => { cancelled = true; };
  }, [applicationAccess, currentUser, enterApplicationAccessDenied, expireSession, format, handleRefreshFailure, lifecycle, redirectAccountUnavailable, refresh, routeBypassesAuth, router, t, tokens]);

  const recheckApplicationAccess = useCallback(async () => {
    if (!tokens || lifecycle.isClosing() || recheckPromise.current) return recheckPromise.current ?? Promise.resolve();
    const generation = lifecycle.generation();
    setAccessRechecking(true);
    setAccessRecheckResult("idle");
    recheckPromise.current = (async () => {
      try {
        const user = await getCurrentUser(apiFetch);
        lifecycle.assertActive(generation);
        applicationAccessRef.current = "granted";
        setCurrentUser(user);
        setApplicationAccess("granted");
        setAuthError(null);
        setAuthReady(true);
        const returnPath = safeReturnPath(deniedReturnPath.current);
        deniedReturnPath.current = "/";
        router.replace(returnPath);
      } catch (error) {
        if (!lifecycle.accepts(generation)) return;
        const apiError = error as Partial<ApiError>;
        if (apiError.status === 403 && apiError.code === "application_access_denied") {
          setAccessRecheckResult("denied");
        } else if (!(apiError.status === 401 || (apiError.status === 403 && unavailableAccountCodes.has(apiError.code ?? "")))) {
          setAccessRecheckResult("failed");
        }
      } finally {
        setAccessRechecking(false);
        recheckPromise.current = null;
      }
    })();
    return recheckPromise.current;
  }, [apiFetch, lifecycle, router, tokens]);

  useEffect(() => {
    if (!authReady || !tokens || !currentUser || routeBypassesAuth) return;
    const url = new URL(window.location.href);
    const draftId = url.searchParams.get("reauthDraftId");
    const nonce = url.searchParams.get("reauthNonce");
    if (draftId && nonce && !restorePrompt) {
      const timer = window.setTimeout(() => setRestorePrompt({ draftId, nonce, returnPath: `${url.pathname}${url.search}` }), 0);
      return () => window.clearTimeout(timer);
    }
  }, [authReady, currentUser, restorePrompt, routeBypassesAuth, tokens]);

  const clearRestoreParams = useCallback(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("reauthDraftId");
    url.searchParams.delete("reauthNonce");
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
    return `${url.pathname}${url.search}`;
  }, []);

  const restoreDraft = useCallback(async () => {
    if (!restorePrompt) return;
    const generation = lifecycle.generation();
    const returnPath = clearRestoreParams();
    const restored = await restoreSessionDraft(apiFetch, restorePrompt.draftId, { return_path: returnPath, nonce: restorePrompt.nonce });
    lifecycle.assertActive(generation);
    window.dispatchEvent(new CustomEvent("nomosmart:restore-session-draft", { detail: { formKey: restored.form_key, payload: restored.payload } }));
    setRestorePrompt(null);
  }, [apiFetch, clearRestoreParams, lifecycle, restorePrompt]);

  const discardDraft = useCallback(async () => {
    if (!restorePrompt) return;
    const returnPath = clearRestoreParams();
    await discardSessionDraft(apiFetch, restorePrompt.draftId, { return_path: returnPath, nonce: restorePrompt.nonce }).catch(() => undefined);
    setRestorePrompt(null);
  }, [apiFetch, clearRestoreParams, restorePrompt]);

  const logout = useCallback(async () => {
    if (logoutPromise.current) return logoutPromise.current;
    recoveryProbe.current?.stop(); recoveryProbe.current = null;
    const idToken = lifecycle.current()?.idToken;
    // Lock the lifecycle synchronously, before clearing React state or awaiting IO.
    const operation = lifecycle.logout({
      refreshUrl: "/api/auth/refresh", revokeUrl: `${apiBaseUrl()}/auth/logout`,
      cleanupUrl: "/api/auth/logout", timeoutMs: authLogoutTimeout(runtimeConfig().authLogoutTimeoutMs),
    });
    authRedirecting.current = true;
    sessionRecoveryStarted.current = true;
    applicationAccessRef.current = "checking";
    setApplicationAccess("checking"); setCurrentUser(null); setTokens(null); setRestorePrompt(null);
    logoutPromise.current = (async () => {
      await operation;
      const config = oidcConfig();
      const url = new URL(`${config.issuer}/protocol/openid-connect/logout`); url.searchParams.set("client_id", config.clientId); url.searchParams.set("post_logout_redirect_uri", config.logoutUrl); if (idToken) url.searchParams.set("id_token_hint", idToken); window.location.assign(url.toString());
    })();
    return logoutPromise.current;
  }, [lifecycle]);
  const installTokens = useCallback((nextTokens: OidcTokens) => {
    if (lifecycle.isClosing()) return false;
    lifecycle.install(nextTokens);
    applicationAccessRef.current = "checking";
    setApplicationAccess("checking");
    setCurrentUser(null);
    setAuthReady(false);
    setAuthError(null);
    setTokens(nextTokens);
    return true;
  }, [lifecycle]);
  const tokenDisplayName = useMemo(() => {
    if (!tokens?.idToken) return "NomoSmart";
    try {
      const claims = decodeJwtPayload(tokens.idToken);
      return String(claims.name || claims.preferred_username || claims.email || "NomoSmart");
    } catch {
      return "NomoSmart";
    }
  }, [tokens]);
  const userDisplayName = currentUser ? formatPersonName(currentUser, locale) || tokenDisplayName : tokenDisplayName;
  const hasPermission = useCallback((moduleName: string, functionName: string, action: PermissionAction) => can(currentUser?.permissions ?? [], moduleName, functionName, action), [currentUser]);
  const canViewModule = useCallback((moduleName: string) => canAnyView(currentUser?.permissions ?? [], moduleName), [currentUser]);
  const localizedAuthError = authError ? localize(authError) : null;
  const value = useMemo(() => ({ tokens, currentUser, applicationAccess, authReady, authError: localizedAuthError, userDisplayName, installTokens, apiFetch, logout, can: hasPermission, canViewModule }), [apiFetch, applicationAccess, authReady, canViewModule, currentUser, hasPermission, installTokens, localizedAuthError, logout, tokens, userDisplayName]);
  const protectedContentReady = Boolean(tokens && authReady && currentUser && applicationAccess === "granted");
  return <AuthContext.Provider value={value}>
    {routeBypassesAuth ? children : connectionRecovery !== "idle" ? <AuthConnectionRecovery busy={connectionRecovery === "checking"} failed={connectionRecovery === "failed"} onRetry={() => retryConnection()} /> : applicationAccess === "denied" && tokens ? (
      <ApplicationAccessDenied
        onLogout={logout}
        onRecheck={recheckApplicationAccess}
        recheckResult={accessRecheckResult}
        rechecking={accessRechecking}
        userDisplayName={userDisplayName}
      />
    ) : protectedContentReady ? children : <><noscript><meta httpEquiv="refresh" content="5;url=/login" /></noscript><main className="auth-loading" role={localizedAuthError ? "alert" : "status"}>{localizedAuthError ? `${t("authLoadFailed")}: ${localizedAuthError}` : t("authCheckingSession")}</main></>}
    {restorePrompt ? <div className="auth-session-modal" role="dialog" aria-modal="true" aria-labelledby="draft-restore-title"><section><h2 id="draft-restore-title">{t("restoreDraftTitle")}</h2><p>{t("restoreDraftHelp")}</p><footer><button className="action-button secondary" onClick={() => { void discardDraft(); }} type="button">{t("discardDraft")}</button><button className="action-button" onClick={() => { void restoreDraft(); }} type="button">{t("restoreDraft")}</button></footer></section></div> : null}
  </AuthContext.Provider>;
}

export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error("useAuth must be used inside AuthProvider"); return value; }
