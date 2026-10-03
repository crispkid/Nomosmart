"use client";

import { ArrowRight, CircleAlert, CircleCheck, Info, LockKeyhole, ShieldCheck } from "lucide-react";
import LoginSessionRedirect from "@/components/LoginSessionRedirect";
import type { LoginNotice } from "@/lib/authState";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

const noticeKeys: Record<LoginNotice, TranslationKey> = {
  session_expired: "loginNoticeSessionExpired",
  logged_out: "loginNoticeLoggedOut",
  logout_incomplete: "loginNoticeLogoutIncomplete",
  login_cancelled: "loginNoticeCancelled",
  account_unavailable: "loginNoticeAccountUnavailable",
  auth_service_unavailable: "loginNoticeServiceUnavailable",
  oidc_error: "oidcCallbackError"
};

export default function LoginContent({ notice, loginChecked }: { notice: LoginNotice | null; loginChecked: boolean }) {
  const { t } = useI18n();
  const NoticeIcon = notice === "logged_out" ? CircleCheck : notice === "login_cancelled" ? Info : CircleAlert;
  const noticeTone = notice === "logged_out" ? "success" : notice === "login_cancelled" ? "info" : "error";

  return <main className="login-page"><LoginSessionRedirect shouldProbe={!notice && !loginChecked} /><section className="login-panel" aria-labelledby="login-title"><aside className="login-context"><div className="brand login-brand"><span className="brand-mark">N</span><span><strong>NomoSmart</strong><small>{t("brandEnterpriseKnowledgeOps")}</small></span></div><div className="login-context-copy"><span className="login-context-icon"><ShieldCheck size={24} /></span><p className="eyebrow">{t("loginSecureEyebrow")}</p><h1 id="login-title">{t("loginTitle")}</h1><p>{t("loginDescription")}</p></div><div className="login-trust-note"><LockKeyhole size={17} /><span>{t("loginTrustNote")}</span></div></aside><div className="login-form-surface"><div className="login-live-entry"><ShieldCheck size={34} /><h2>{t("loginLiveHeading")}</h2><p>{t("loginLiveHelp")}</p>{notice ? <div className={`login-auth-notice ${noticeTone}`} role={noticeTone === "error" ? "alert" : "status"}><NoticeIcon size={18} /><span>{t(noticeKeys[notice])}</span></div> : null}<a className="login-submit" href="/api/auth/start">{t("loginWithKeycloak")}<ArrowRight size={18} /></a></div></div></section></main>;
}
