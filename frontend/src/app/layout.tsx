import type { Metadata } from "next";
import { Noto_Sans_TC } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { AuthProvider } from "@/components/AuthProvider";
import { LocaleProvider } from "@/components/LocaleProvider";
import { graphCacheInteger } from "@/lib/graphLayoutCache";
import { feedbackInteger } from "@/lib/feedback";
import { htmlLangForLocale, isSupportedLocale, localePreferenceKey } from "@/lib/i18n";
import type { RuntimeConfig } from "@/lib/runtimeConfig";
import { authLogoutTimeout } from "@/lib/authSessionLifecycle";
import { uploadWaitNoticeMs } from "@/lib/uploadProgress";
import { protectedPageMatchers } from "@/lib/applicationRoutes";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";

// OPT424-037: a slow hydration must not sign a valid user out. After 5 s the
// watchdog offers reload or sign-in instead of redirecting on its own.
function hydrationWatchdog(locale: "zh" | "en"): string {
  const text = locale === "en" ? en : zh;
  const config = JSON.stringify({
    ...protectedPageMatchers,
    message: text.hydrationStalledMessage,
    reload: text.hydrationStalledReload,
    login: text.hydrationStalledLogin,
  }).replace(/</g, "\\u003c");
  return `window.__NOMOSMART_AUTH_HYDRATED__=false;window.setTimeout(function(){var c=${config};var p=window.location.pathname;if(p.length>1){p=p.replace(/\\/$/,"")}var guarded=c.staticPages.indexOf(p)>=0||new RegExp(c.projectPage).test(p)||new RegExp(c.approvalPage).test(p);if(!guarded||window.__NOMOSMART_AUTH_HYDRATED__||document.getElementById("nomosmart-hydration-stalled"))return;var box=document.createElement("div");box.id="nomosmart-hydration-stalled";box.className="hydration-stalled";box.setAttribute("role","alert");var msg=document.createElement("span");msg.textContent=c.message;var reload=document.createElement("button");reload.type="button";reload.textContent=c.reload;reload.onclick=function(){window.location.reload()};var login=document.createElement("a");login.href="/login";login.textContent=c.login;box.appendChild(msg);box.appendChild(reload);box.appendChild(login);document.body.appendChild(box)},5000);`;
}

// OPT424-030: self-hosted at build time by next/font; only regular/medium/bold.
const notoSansTC = Noto_Sans_TC({
  weight: ["400", "500", "700"],
  display: "swap",
  preload: false,
  variable: "--font-noto-sans-tc",
});

export const metadata: Metadata = {
  description: "Enterprise knowledge management platform",
  icons: { icon: { url: "/favicon.ico", type: "image/x-icon", sizes: "16x16 32x32" } }
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const preference = (await cookies()).get(localePreferenceKey)?.value ?? null;
  const initialLocale = isSupportedLocale(preference) ? preference : "zh";
  const runtimeConfig: RuntimeConfig = {
    graphLayoutCacheMaxEntries: graphCacheInteger(process.env.FRONTEND_GRAPH_LAYOUT_CACHE_MAX_ENTRIES, 8, 64),
    graphLayoutCacheMaxNodes: graphCacheInteger(process.env.FRONTEND_GRAPH_LAYOUT_CACHE_MAX_NODES, 8000, 128000),
    authLogoutTimeoutMs: authLogoutTimeout(process.env.FRONTEND_AUTH_LOGOUT_TIMEOUT_MS),
    uploadWaitNoticeMs: uploadWaitNoticeMs(process.env.FRONTEND_UPLOAD_WAIT_NOTICE_MS),
    feedbackToastDurationMs: feedbackInteger(process.env.FRONTEND_FEEDBACK_TOAST_DURATION_MS, 5000, 3000, 20000),
    feedbackToastVisibleLimit: feedbackInteger(process.env.FRONTEND_FEEDBACK_TOAST_VISIBLE_LIMIT, 2, 1, 3),
    feedbackRecentLimit: feedbackInteger(process.env.FRONTEND_FEEDBACK_RECENT_LIMIT, 20, 1, 100),
    appOrigin: process.env.FRONTEND_APP_ORIGIN ?? process.env.NEXT_PUBLIC_APP_ORIGIN ?? "http://127.0.0.1:3000",
    apiBaseUrl: process.env.FRONTEND_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend",
    oidcIssuerUrl: process.env.FRONTEND_OIDC_ISSUER_URL ?? process.env.NEXT_PUBLIC_OIDC_ISSUER_URL ?? "",
    oidcClientId: process.env.FRONTEND_OIDC_CLIENT_ID ?? process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "nomosmart-frontend",
    oidcAudience: process.env.FRONTEND_OIDC_AUDIENCE ?? process.env.NEXT_PUBLIC_OIDC_AUDIENCE ?? "nomosmart-backend",
  };
  const serializedConfig = JSON.stringify(runtimeConfig).replace(/</g, "\\u003c");
  return (
    <html lang={htmlLangForLocale(initialLocale)} className={notoSansTC.variable}>
      <body>
        <script
          id="nomosmart-runtime-config"
          dangerouslySetInnerHTML={{ __html: `window.__NOMOSMART_RUNTIME_CONFIG__=${serializedConfig};` }}
        />
        <script
          id="nomosmart-auth-hydration-watchdog"
          dangerouslySetInnerHTML={{
            __html: hydrationWatchdog(initialLocale === "en" ? "en" : "zh")
          }}
        />
        <LocaleProvider initialLocale={initialLocale}><AuthProvider>{children}</AuthProvider></LocaleProvider>
      </body>
    </html>
  );
}
