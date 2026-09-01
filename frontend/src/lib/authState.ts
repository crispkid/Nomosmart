import { NextRequest, NextResponse } from "next/server";
import { oidcConfig, safeReturnPath } from "@/lib/oidc";

export const AUTH_COOKIES = {
  pkce: "nomosmart_pkce",
  state: "nomosmart_state",
  nonce: "nomosmart_nonce",
  returnTo: "nomosmart_return",
  flow: "nomosmart_auth_flow",
  loginNotice: "nomosmart_login_notice",
  loginChecked: "nomosmart_login_checked"
} as const;

export type AuthFlow = "silent" | "interactive" | "session_expired";
export type LoginNotice = "session_expired" | "logged_out" | "login_cancelled" | "account_unavailable" | "auth_service_unavailable" | "oidc_error";
export type LoginRecoveryMode = "anonymous" | LoginNotice;

const loginNotices = new Set<LoginNotice>(["session_expired", "logged_out", "login_cancelled", "account_unavailable", "auth_service_unavailable", "oidc_error"]);
const recoveryModes = new Set<LoginRecoveryMode>(["anonymous", ...loginNotices]);

export function parseAuthFlow(value: string | null | undefined): AuthFlow | null {
  return value === "silent" || value === "interactive" || value === "session_expired" ? value : null;
}

export function parseLoginNotice(value: string | null | undefined): LoginNotice | null {
  return value && loginNotices.has(value as LoginNotice) ? value as LoginNotice : null;
}

export function parseLoginRecoveryMode(value: string | null | undefined): LoginRecoveryMode {
  return value && recoveryModes.has(value as LoginRecoveryMode) ? value as LoginRecoveryMode : "oidc_error";
}

export function authCookieOptions(maxAge = 300) {
  return { httpOnly: true, sameSite: "lax" as const, secure: process.env.NODE_ENV === "production", path: "/", maxAge };
}

export function clearAuthorizationState(response: NextResponse, options: { keepReturn?: boolean; keepNotice?: boolean; keepLoginChecked?: boolean } = {}) {
  for (const name of [AUTH_COOKIES.pkce, AUTH_COOKIES.state, AUTH_COOKIES.nonce, AUTH_COOKIES.flow]) response.cookies.delete(name);
  if (!options.keepReturn) response.cookies.delete(AUTH_COOKIES.returnTo);
  if (!options.keepNotice) response.cookies.delete(AUTH_COOKIES.loginNotice);
  if (!options.keepLoginChecked) response.cookies.delete(AUTH_COOKIES.loginChecked);
}

export function canonicalLoginUrl(): URL {
  const url = new URL(oidcConfig().logoutUrl);
  url.pathname = "/login";
  url.search = "";
  url.hash = "";
  return url;
}

export function createLoginRecoveryResponse(request: NextRequest, mode: LoginRecoveryMode, requestedReturnTo?: string | null): NextResponse {
  const response = NextResponse.redirect(canonicalLoginUrl());
  const preserveExistingReturn = mode === "anonymous" || mode === "login_cancelled" || mode === "auth_service_unavailable";
  clearAuthorizationState(response, { keepReturn: preserveExistingReturn || mode === "session_expired" });

  if (mode === "session_expired") {
    response.cookies.set(AUTH_COOKIES.returnTo, safeReturnPath(requestedReturnTo), authCookieOptions());
  }
  if (mode === "anonymous") {
    response.cookies.delete(AUTH_COOKIES.loginNotice);
  } else {
    response.cookies.set(AUTH_COOKIES.loginNotice, mode, authCookieOptions(120));
  }
  response.cookies.set(AUTH_COOKIES.loginChecked, "1", authCookieOptions(120));
  response.headers.set("cache-control", "no-store");
  return response;
}
