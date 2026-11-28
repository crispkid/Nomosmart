"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, CheckSquare, Eye, EyeOff, FileText, KeyRound, Layers, LockKeyhole, MessageSquare, UserRound } from "lucide-react";
import { FeedbackMessage } from "./FeedbackMessage";
import { useAuth } from "./AuthProvider";
import { BrandMark } from "./BrandMark";
import { LanguageToggle } from "./LanguageToggle";
import LoginSessionRedirect from "./LoginSessionRedirect";
import type { LoginNotice } from "@/lib/authState";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { BrowserTitle } from "@/lib/browserTitle";
import { apiBaseUrl, safeReturnPath } from "@/lib/oidc";
import { useReadResource } from "@/lib/useReadResource";

const noticeKeys: Record<LoginNotice, TranslationKey> = {
  session_expired: "loginNoticeSessionExpired", logged_out: "loginNoticeLoggedOut", logout_incomplete: "loginNoticeLogoutIncomplete", login_cancelled: "loginNoticeCancelled", account_unavailable: "loginNoticeAccountUnavailable", auth_service_unavailable: "loginNoticeServiceUnavailable", oidc_error: "oidcCallbackError"
};
type PublicConfig = { mode: "oidc" | "ldap"; display_name: string };

/** CHG-495 M06: brand panel process sketch (document → chunk → review → chat). */
const processSteps = [
  { key: "loginProcessDocument", icon: FileText, tone: "info" },
  { key: "loginProcessChunk", icon: Layers, tone: "accent" },
  { key: "loginProcessReview", icon: CheckSquare, tone: "amber" },
  { key: "loginProcessChat", icon: MessageSquare, tone: "violet" },
] as const;

async function readPublicConfig(signal: AbortSignal): Promise<PublicConfig> {
  const response = await fetch(`${apiBaseUrl()}/auth/config`, { cache: "no-store", credentials: "same-origin", signal });
  if (!response.ok) throw new Error("configuration_unavailable");
  return await response.json() as PublicConfig;
}

export default function LoginContent({ notice, loginChecked }: { notice: LoginNotice | null; loginChecked: boolean }) {
  const { t } = useI18n();
  const { logout } = useAuth();
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [emergency, setEmergency] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [returnTo, setReturnTo] = useState("/");

  // OPT424-035: the public sign-in configuration is a read resource; a failed read shows the login error.
  const configRead = useReadResource<PublicConfig>(readPublicConfig, "auth-config", true, { onError: () => setError(true) });
  const config = configRead.data;
  useEffect(() => {
    const timer = window.setTimeout(() => setReturnTo(safeReturnPath(new URL(window.location.href).searchParams.get("returnTo"))), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return;
    const form = event.currentTarget, fields = new FormData(form);
    setPasswordVisible(false);
    setBusy(true); setError(false);
    try {
      const response = await fetch(`${apiBaseUrl()}/auth/${emergency ? "emergency/login" : "login"}`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: fields.get("username"), password: fields.get("password") }), cache: "no-store" });
      form.reset();
      if (!response.ok) throw new Error("login_failed");
      window.location.replace(returnTo);
    } catch { setError(true); setBusy(false); }
  }

  function switchLoginEntry() {
    setEmergency(!emergency);
    setPasswordVisible(false);
    setError(false);
  }

  // C5: only the method of the configured sign-in mode is shown (or the emergency form when chosen).
  const passwordForm = emergency || config?.mode === "ldap";

  return <main className="login-page">
    <BrowserTitle label={t("workspaceLoginTitle")} />
    <LoginSessionRedirect shouldProbe={!notice && !loginChecked} />
    <section className="login-brand-panel" aria-labelledby="login-title">
      <div className="login-brand"><BrandMark size={28} /><span>NomoSmart</span></div>
      <div className="login-brand-copy">
        <h1 id="login-title">{t("loginBrandTagline")}</h1>
        <p>{t("loginWorkspaceDescription")}</p>
        <ol className="login-process" aria-label={t("loginProcessLabel")}>
          {processSteps.map(({ key, icon: Icon, tone }, index) => <li key={key}>
            {index > 0 ? <ArrowRight className="login-process-arrow" aria-hidden size={18} /> : null}
            <span className="login-process-step"><span className={`login-process-mark tone-${tone}`}><Icon aria-hidden size={20} /></span>{t(key)}</span>
          </li>)}
        </ol>
      </div>
    </section>
    <section className="login-form-panel" aria-labelledby="login-entry-title">
      <div className="login-toolbar"><LanguageToggle /></div>
      <div className="login-live-entry">
        <header className="login-entry-heading">
          <div className="login-entry-title-row">
            <h2 id="login-entry-title">{emergency ? t("protocolEmergencySignIn") : config?.display_name || t("loginWelcomeTitle")}</h2>
            {emergency ? <span className="login-emergency-badge">{t("loginEmergencyBadge")}</span> : null}
          </div>
          <p>{emergency ? t("protocolEmergencyHelp") : config ? t(config.mode === "ldap" ? "loginDirectoryHelp" : "loginOidcHelp") : t("protocolLoginDescription")}</p>
        </header>
        {notice || error || emergency ? <div className="login-feedback">
          {emergency ? <FeedbackMessage tone="warning" announce={false} title={t("loginEmergencyBadge")}>{t("loginEmergencyNotice")}</FeedbackMessage> : null}
          {notice ? <FeedbackMessage tone={notice === "logged_out" ? "success" : "warning"}>{t(noticeKeys[notice])}</FeedbackMessage> : null}
          {error ? <FeedbackMessage tone="error">{t("protocolLoginFailed")}</FeedbackMessage> : null}
        </div> : null}
        {passwordForm ? <form key={emergency ? "emergency" : "directory"} className={`login-form${error ? " has-error" : ""}`} onSubmit={signIn} aria-busy={busy}>
          <div className="login-field">
            <label htmlFor="login-username">{t("protocolUsername")}</label>
            <div className="login-input-wrap">
              <UserRound className="login-input-icon" aria-hidden size={18} />
              <input id="login-username" autoComplete="username" autoCapitalize="none" spellCheck={false} name="username" placeholder={t("loginUsernamePlaceholder")} required maxLength={255} disabled={busy} />
            </div>
          </div>
          <div className="login-field">
            <label htmlFor="login-password">{t("protocolPassword")}</label>
            <div className="login-input-wrap login-password-wrap">
              <LockKeyhole className="login-input-icon" aria-hidden size={18} />
              <input id="login-password" autoComplete="current-password" type={passwordVisible ? "text" : "password"} name="password" placeholder={t("loginPasswordPlaceholder")} required maxLength={4096} disabled={busy} />
              <button className="login-password-toggle" type="button" aria-label={t(passwordVisible ? "loginHidePassword" : "loginShowPassword")} aria-pressed={passwordVisible} aria-controls="login-password" onClick={() => setPasswordVisible(!passwordVisible)} disabled={busy}>
                {passwordVisible ? <EyeOff aria-hidden size={18} /> : <Eye aria-hidden size={18} />}
              </button>
            </div>
          </div>
          <button className="login-submit" disabled={busy} type="submit">{t(busy ? "authCheckingSession" : "protocolSignIn")}<ArrowRight aria-hidden size={18} /></button>
        </form> : config ? <div className="login-oidc-action"><a className="login-submit" href={`/api/auth/start?returnTo=${encodeURIComponent(returnTo)}`}>{t("protocolEnterpriseSignIn")}<ArrowRight aria-hidden size={18} /></a></div> : <p className="login-config-status" role="status">{t("authCheckingSession")}</p>}
        <p className="login-trust-note"><LockKeyhole aria-hidden size={14} /><span>{t("protocolIdleHelp")}</span></p>
        {notice === "logout_incomplete" ? <button className="action-button secondary login-logout-retry" type="button" onClick={() => { void logout(); }}>{t("logout")}</button> : null}
        <div className="login-secondary-entry">
          <button className="login-emergency-link" type="button" onClick={switchLoginEntry} disabled={busy}><KeyRound aria-hidden size={16} />{t(emergency ? "protocolBackToSignIn" : "protocolEmergencySignIn")}</button>
        </div>
      </div>
    </section>
  </main>;
}
