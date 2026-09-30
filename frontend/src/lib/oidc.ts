export type OidcConfig = { issuer: string; internalIssuer: string; clientId: string; audience: string; callbackUrl: string; logoutUrl: string };
export type OidcTokens = { accessToken: string; refreshToken: string; idToken?: string; expiresAt: number };

function authRuntimeConfig() {
  if (typeof window !== "undefined" && window.__NOMOSMART_RUNTIME_CONFIG__) {
    return { ...window.__NOMOSMART_RUNTIME_CONFIG__, oidcInternalIssuerUrl: window.__NOMOSMART_RUNTIME_CONFIG__.oidcIssuerUrl };
  }
  return {
    appOrigin: process.env.FRONTEND_APP_ORIGIN ?? "http://127.0.0.1:3000",
    apiBaseUrl: process.env.FRONTEND_PUBLIC_API_BASE_URL ?? "/api/backend",
    oidcIssuerUrl: process.env.FRONTEND_OIDC_ISSUER_URL ?? "http://127.0.0.1:8080/realms/nomosmart",
    oidcInternalIssuerUrl: process.env.FRONTEND_OIDC_INTERNAL_ISSUER_URL ?? process.env.FRONTEND_OIDC_ISSUER_URL ?? "http://127.0.0.1:8080/realms/nomosmart",
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

export function base64Url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function randomUrlToken(size = 32): string { return base64Url(crypto.getRandomValues(new Uint8Array(size))); }
export async function pkceChallenge(verifier: string): Promise<string> { return base64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)))); }

export function authorizationUrl(config: OidcConfig, input: { state: string; nonce: string; challenge: string; prompt?: string }): string {
  const url = new URL(`${config.issuer}/protocol/openid-connect/auth`);
  for (const [key, value] of Object.entries({ client_id: config.clientId, redirect_uri: config.callbackUrl, response_type: "code", scope: "openid profile email", state: input.state, nonce: input.nonce, code_challenge: input.challenge, code_challenge_method: "S256" })) url.searchParams.set(key, value);
  if (input.prompt) url.searchParams.set("prompt", input.prompt);
  return url.toString();
}

export function decodeJwtPayload(token: string): Record<string, unknown> {
  const part = token.split(".")[1];
  if (!part) throw new Error("invalid_id_token");
  return JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "="))) as Record<string, unknown>;
}
