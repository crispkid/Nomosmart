import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/AuthProvider";
import type { RuntimeConfig } from "@/lib/runtimeConfig";
import { authLogoutTimeout } from "@/lib/authSessionLifecycle";
import { uploadWaitNoticeMs } from "@/lib/uploadProgress";

export const metadata: Metadata = {
  title: "NomoSmart",
  description: "Enterprise knowledge management platform",
  icons: { icon: { url: "/favicon.ico", type: "image/x-icon", sizes: "16x16 32x32" } }
};

export const dynamic = "force-dynamic";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const runtimeConfig: RuntimeConfig = {
    authLogoutTimeoutMs: authLogoutTimeout(process.env.FRONTEND_AUTH_LOGOUT_TIMEOUT_MS),
    uploadWaitNoticeMs: uploadWaitNoticeMs(process.env.FRONTEND_UPLOAD_WAIT_NOTICE_MS),
    appOrigin: process.env.FRONTEND_APP_ORIGIN ?? process.env.NEXT_PUBLIC_APP_ORIGIN ?? "http://127.0.0.1:3000",
    apiBaseUrl: process.env.FRONTEND_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/backend",
    oidcIssuerUrl: process.env.FRONTEND_OIDC_ISSUER_URL ?? process.env.NEXT_PUBLIC_OIDC_ISSUER_URL ?? "http://127.0.0.1:8080/realms/nomosmart",
    oidcClientId: process.env.FRONTEND_OIDC_CLIENT_ID ?? process.env.NEXT_PUBLIC_OIDC_CLIENT_ID ?? "nomosmart-frontend",
    oidcAudience: process.env.FRONTEND_OIDC_AUDIENCE ?? process.env.NEXT_PUBLIC_OIDC_AUDIENCE ?? "nomosmart-backend",
  };
  const serializedConfig = JSON.stringify(runtimeConfig).replace(/</g, "\\u003c");
  return (
    <html lang="zh-Hant">
      <body>
        <script
          id="nomosmart-runtime-config"
          dangerouslySetInnerHTML={{ __html: `window.__NOMOSMART_RUNTIME_CONFIG__=${serializedConfig};` }}
        />
        <script
          id="nomosmart-auth-hydration-watchdog"
          dangerouslySetInnerHTML={{
            __html: "window.__NOMOSMART_AUTH_HYDRATED__=false;window.setTimeout(function(){var path=window.location.pathname;var protectedPath=path==='/'||path==='/projects'||path.indexOf('/project/')===0||path==='/approve'||path.indexOf('/approve/')===0||path==='/reports'||path==='/system'||path==='/api-docs'||path==='/access-denied';if(protectedPath&&!window.__NOMOSMART_AUTH_HYDRATED__){window.location.replace('/login')}},5000);"
          }}
        />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
