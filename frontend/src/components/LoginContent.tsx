"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, KeyRound, LockKeyhole, UserRound } from "lucide-react";
import { FeedbackMessage } from "./FeedbackMessage";
import { useAuth } from "./AuthProvider";
import LoginKnowledgeIllustration from "./LoginKnowledgeIllustration";
import LoginLanguageMenu from "./LoginLanguageMenu";
import LoginSessionRedirect from "./LoginSessionRedirect";
import type { LoginNotice } from "@/lib/authState";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { BrowserTitle } from "@/lib/browserTitle";
import { apiBaseUrl, safeReturnPath } from "@/lib/oidc";

const noticeKeys: Record<LoginNotice, TranslationKey> = {
  session_expired: "loginNoticeSessionExpired", logged_out: "loginNoticeLoggedOut", logout_incomplete: "loginNoticeLogoutIncomplete", login_cancelled: "loginNoticeCancelled", account_unavailable: "loginNoticeAccountUnavailable", auth_service_unavailable: "loginNoticeServiceUnavailable", oidc_error: "oidcCallbackError"
};
type PublicConfig = { mode: "oidc" | "ldap"; display_name: string };

export default function LoginContent({ notice, loginChecked }: { notice: LoginNotice | null; loginChecked: boolean }) {
  const { t } = useI18n();
  const { logout } = useAuth();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [emergency, setEmergency] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [returnTo, setReturnTo] = useState("/");

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => setReturnTo(safeReturnPath(new URL(window.location.href).searchParams.get("returnTo"))), 0);
    void fetch(`${apiBaseUrl()}/auth/config`, { cache: "no-store", credentials: "same-origin", signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error("configuration_unavailable");
      setConfig(await response.json() as PublicConfig);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => { controller.abort(); window.clearTimeout(timer); };
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

  const passwordForm = emergency || config?.mode === "ldap";

  return <main className="login-page">
    <BrowserTitle label={t("workspaceLoginTitle")} />
    <LoginSessionRedirect shouldProbe={!notice && !loginChecked} />
    <div className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-toolbar"><LoginLanguageMenu /></div>
        <aside className="login-context">
          <div className="brand login-brand"><span className="brand-mark">N</span><span><strong>NomoSmart</strong><small>{t("brandEnterpriseKnowledgeOps")}</small></span></div>
          <div className="login-context-copy">
            <h1 id="login-title"><span>{t("loginKnowledgeHeading")}</span><span>{t("loginGovernanceHeading")}</span></h1>
            <p>{t("loginWorkspaceDescription")}</p>
          </div>
          <LoginKnowledgeIllustration />
        </aside>
        <div className="login-form-surface">
          <div className="login-live-entry">
            <header className="login-entry-heading">
              <h2>{emergency ? t("protocolEmergencySignIn") : config?.display_name || t("loginWelcomeTitle")}</h2>
              <p>{emergency ? t("protocolEmergencyHelp") : config ? t(config.mode === "ldap" ? "loginDirectoryHelp" : "loginOidcHelp") : t("protocolLoginDescription")}</p>
            </header>
            {notice || error ? <div className="login-feedback">
              {notice ? <FeedbackMessage tone={notice === "logged_out" ? "success" : "warning"}>{t(noticeKeys[notice])}</FeedbackMessage> : null}
              {error ? <FeedbackMessage tone="error">{t("protocolLoginFailed")}</FeedbackMessage> : null}
            </div> : null}
            {passwordForm ? <form key={emergency ? "emergency" : "directory"} className={`login-form${error ? " has-error" : ""}`} onSubmit={signIn} aria-busy={busy}>
              <div className="login-fields">
                <div className="login-field">
                  <label htmlFor="login-username">{t("protocolUsername")}</label>
                  <div className="login-input-wrap">
                    <UserRound className="login-input-icon" aria-hidden size={21} />
                    <input id="login-username" autoComplete="username" autoCapitalize="none" spellCheck={false} name="username" placeholder={t("loginUsernamePlaceholder")} required maxLength={255} disabled={busy} />
                  </div>
                </div>
                <div className="login-field">
                  <label htmlFor="login-password">{t("protocolPassword")}</label>
                  <div className="login-input-wrap login-password-wrap">
                    <LockKeyhole className="login-input-icon" aria-hidden size={21} />
                    <input id="login-password" autoComplete="current-password" type={passwordVisible ? "text" : "password"} name="password" placeholder={t("loginPasswordPlaceholder")} required maxLength={4096} disabled={busy} />
                    <button className="login-password-toggle" type="button" aria-label={t(passwordVisible ? "loginHidePassword" : "loginShowPassword")} aria-pressed={passwordVisible} aria-controls="login-password" onClick={() => setPasswordVisible(!passwordVisible)} disabled={busy}>
                      {passwordVisible ? <EyeOff aria-hidden size={21} /> : <Eye aria-hidden size={21} />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="login-actions">
                <button className="login-submit" disabled={busy} type="submit">{t(busy ? "authCheckingSession" : "protocolSignIn")}<ArrowRight aria-hidden size={20} /></button>
              </div>
            </form> : config ? <div className="login-oidc-action"><a className="login-submit" href={`/api/auth/start?returnTo=${encodeURIComponent(returnTo)}`}>{t("protocolEnterpriseSignIn")}<ArrowRight aria-hidden size={20} /></a></div> : <p className="login-config-status" role="status">{t("authCheckingSession")}</p>}
            <p className="login-trust-note"><LockKeyhole aria-hidden size={15} /><span>{t("protocolIdleHelp")}</span></p>
            {notice === "logout_incomplete" ? <button className="action-button secondary" type="button" onClick={() => { void logout(); }}>{t("logout")}</button> : null}
            <div className="login-secondary-entry">
              <button className="login-emergency-link" type="button" onClick={switchLoginEntry} disabled={busy}><KeyRound aria-hidden size={19} />{t(emergency ? "protocolBackToSignIn" : "protocolEmergencySignIn")}</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </main>;
}
