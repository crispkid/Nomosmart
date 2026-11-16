type OidcConfig = { issuer: string; internalIssuer: string; clientId: string; audience: string; callbackUrl: string; logoutUrl: string };

function authRuntimeConfig() {
  if (typeof window !== "undefined" && window.__NOMOSMART_RUNTIME_CONFIG__) {
    return { ...window.__NOMOSMART_RUNTIME_CONFIG__, oidcInternalIssuerUrl: window.__NOMOSMART_RUNTIME_CONFIG__.oidcIssuerUrl };
  }
  return {
    appOrigin: process.env.FRONTEND_APP_ORIGIN ?? "http://127.0.0.1:3000",
    apiBaseUrl: process.env.FRONTEND_PUBLIC_API_BASE_URL ?? "/api/backend",
    oidcIssuerUrl: process.env.FRONTEND_OIDC_ISSUER_URL ?? "",
    oidcInternalIssuerUrl: process.env.FRONTEND_OIDC_INTERNAL_ISSUER_URL ?? process.env.FRONTEND_OIDC_ISSUER_URL ?? "",
    oidcClientId: process.env.FRONTEND_OIDC_CLIENT_ID ?? "nomosmart-frontend",
    oidcAudience: process.env.FRONTEND_OIDC_AUDIENCE ?? "nomosmart-backend",
  };
}

export function oidcConfig(): OidcConfig {
  const runtime = authRuntimeConfig();
  const origin = runtime.appOrigin.replace(/\/$/, "");
  return {
    issuer: runtime.oidcIssuerUrl.replace(/\/$/, ""),
    internalIssuer: runtime.oidcInternalIssuerUrl.replace(/\/$/, ""),
    clientId: runtime.oidcClientId,
    audience: runtime.oidcAudience,
    callbackUrl: `${origin}/auth/callback`, logoutUrl: `${origin}/login`
  };
}

export function apiBaseUrl(): string {
  return authRuntimeConfig().apiBaseUrl.replace(/\/$/, "");
}

export function safeReturnPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  try {
    const parsed = new URL(value, "http://nomosmart.local");
    if (parsed.origin !== "http://nomosmart.local") return "/";
    const path = parsed.pathname;
    const knownRoute = path === "/" || path === "/projects" || path.startsWith("/project/") || path === "/approve" || path.startsWith("/approve/") || path === "/reports" || path === "/system" || path === "/api-docs";
    if (!knownRoute || path === "/login" || path.startsWith("/auth/callback") || path.startsWith("/api/auth/")) return "/";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/";
  }
}
