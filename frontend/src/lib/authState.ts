import { NextRequest, NextResponse } from "next/server";
import { oidcConfig, safeReturnPath } from "@/lib/oidc";
import { parseAuthFlowId } from "@/lib/authFlowRecovery";

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
export type LoginNotice = "session_expired" | "logged_out" | "logout_incomplete" | "login_cancelled" | "account_unavailable" | "auth_service_unavailable" | "oidc_error";
export type LoginRecoveryMode = "anonymous" | LoginNotice;

const loginNotices = new Set<LoginNotice>(["session_expired", "logged_out", "logout_incomplete", "login_cancelled", "account_unavailable", "auth_service_unavailable", "oidc_error"]);
const recoveryModes = new Set<LoginRecoveryMode>(["anonymous", ...loginNotices]);

export const AUTH_FLOW_COOKIE_PREFIX = "nomosmart_oidc_v2_";
export const AUTH_FLOW_TTL_SECONDS = 300;
export const AUTH_FLOW_LIMIT = 4;
const maxFlowCookieBytes = 1536;
const maxReturnBytes = 512;
const statePattern = /^[A-Za-z0-9_-]{43}$/;
const verifierPattern = /^[A-Za-z0-9_-]{64}$/;
const packetKeys = ["version", "state", "verifier", "nonce", "flow", "returnTo", "createdAt", "expiresAt"];

type AuthCookieStore = {
  get: (name: string) => { value: string } | undefined;
  getAll: () => { name: string; value: string }[];
};
export type AuthorizationPacket = {
  version: 2;
  state: string;
  verifier: string;
  nonce: string;
  flow: AuthFlow;
  returnTo: string;
  createdAt: number;
  expiresAt: number;
};
export type OwnedAuthorizationState = { name: string; packet: AuthorizationPacket };

export function boundedReturnPath(value: string | null | undefined): string {
  const path = safeReturnPath(value);
  return Buffer.byteLength(path, "utf8") <= maxReturnBytes ? path : "/";
}

export async function authorizationFlowId(state: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(state));
  return Buffer.from(hash).toString("hex");
}

export function encodeAuthorizationPacket(packet: AuthorizationPacket): string {
  const encoded = Buffer.from(JSON.stringify(packet), "utf8").toString("base64url");
  if (Buffer.byteLength(encoded) > maxFlowCookieBytes) throw new Error("oidc_packet_too_large");
  return encoded;
}

function parseAuthorizationPacket(value: string, now: number): AuthorizationPacket | null {
  if (Buffer.byteLength(value) > maxFlowCookieBytes || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const decoded = Buffer.from(value, "base64url");
    if (decoded.toString("base64url") !== value) return null;
    const data: unknown = JSON.parse(decoded.toString("utf8"));
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const packet = data as Record<string, unknown>;
    if (Object.keys(packet).length !== packetKeys.length || !packetKeys.every((key) => key in packet)) return null;
    if (packet.version !== 2 || typeof packet.state !== "string" || !statePattern.test(packet.state)
      || typeof packet.verifier !== "string" || !verifierPattern.test(packet.verifier)
      || typeof packet.nonce !== "string" || !statePattern.test(packet.nonce)
      || !parseAuthFlow(typeof packet.flow === "string" ? packet.flow : null)
      || typeof packet.returnTo !== "string" || boundedReturnPath(packet.returnTo) !== packet.returnTo
      || typeof packet.createdAt !== "number" || !Number.isSafeInteger(packet.createdAt) || packet.createdAt < 0 || packet.createdAt > now
      || typeof packet.expiresAt !== "number" || packet.expiresAt !== packet.createdAt + AUTH_FLOW_TTL_SECONDS * 1000
      || packet.expiresAt <= now) return null;
    return packet as AuthorizationPacket;
  } catch {
    return null;
  }
}

export async function readAuthorizationOwner(store: AuthCookieStore, flowId: unknown, now = Date.now()): Promise<OwnedAuthorizationState | null> {
  const id = parseAuthFlowId(flowId);
  if (!id) return null;
  const name = AUTH_FLOW_COOKIE_PREFIX + id;
  const value = store.get(name)?.value;
  const packet = value ? parseAuthorizationPacket(value, now) : null;
  if (!packet || await authorizationFlowId(packet.state) !== id) return null;
  return { name, packet };
}

export async function readAuthorizationState(store: AuthCookieStore, state: unknown): Promise<OwnedAuthorizationState | null> {
  if (typeof state !== "string" || !statePattern.test(state)) return null;
  const owner = await readAuthorizationOwner(store, await authorizationFlowId(state));
  return owner?.packet.state === state ? owner : null;
}

export async function inspectAuthorizationStates(store: AuthCookieStore): Promise<{ active: OwnedAuthorizationState[]; obsoleteNames: string[] }> {
  const now = Date.now();
  const candidates = store.getAll().filter(({ name }) => name.startsWith(AUTH_FLOW_COOKIE_PREFIX) && parseAuthFlowId(name.slice(AUTH_FLOW_COOKIE_PREFIX.length)));
  const owners = await Promise.all(candidates.map(({ name }) => readAuthorizationOwner(store, name.slice(AUTH_FLOW_COOKIE_PREFIX.length), now)));
  return {
    active: owners.filter((owner): owner is OwnedAuthorizationState => owner !== null),
    obsoleteNames: candidates.filter((_, index) => !owners[index]).map(({ name }) => name),
  };
}

export function expireAuthCookie(response: NextResponse, name: string) {
  response.cookies.set(name, "", { ...authCookieOptions(0), expires: new Date(0) });
}

export function clearLegacyAuthorizationState(response: NextResponse) {
  for (const name of [AUTH_COOKIES.pkce, AUTH_COOKIES.state, AUTH_COOKIES.nonce, AUTH_COOKIES.flow]) expireAuthCookie(response, name);
}

export function clearLoginFlash(response: NextResponse) {
  for (const name of [AUTH_COOKIES.returnTo, AUTH_COOKIES.loginNotice, AUTH_COOKIES.loginChecked]) expireAuthCookie(response, name);
}

export function clearAuthorizationSnapshot(response: NextResponse, store: AuthCookieStore) {
  const knownNames = new Set<string>(Object.values(AUTH_COOKIES));
  for (const { name } of store.getAll()) {
    if (knownNames.has(name) || name.startsWith(AUTH_FLOW_COOKIE_PREFIX) && parseAuthFlowId(name.slice(AUTH_FLOW_COOKIE_PREFIX.length))) expireAuthCookie(response, name);
  }
}

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

export function clearAuthorizationState(response: NextResponse, owner: OwnedAuthorizationState | null) {
  if (owner) expireAuthCookie(response, owner.name);
}

export function canonicalLoginUrl(): URL {
  const url = new URL(oidcConfig().logoutUrl);
  url.pathname = "/login";
  url.search = "";
  url.hash = "";
  return url;
}

export function createLoginRecoveryResponse(_request: NextRequest, mode: LoginRecoveryMode, requestedReturnTo?: string | null, owner: OwnedAuthorizationState | null = null): NextResponse {
  const response = NextResponse.redirect(canonicalLoginUrl());
  const preserveExistingReturn = mode === "anonymous" || mode === "login_cancelled" || mode === "auth_service_unavailable";
  clearAuthorizationState(response, owner);
  clearLegacyAuthorizationState(response);

  if (mode === "session_expired" || preserveExistingReturn && (owner || requestedReturnTo != null)) {
    response.cookies.set(AUTH_COOKIES.returnTo, boundedReturnPath(owner?.packet.returnTo ?? requestedReturnTo), authCookieOptions());
  } else if (!preserveExistingReturn) {
    expireAuthCookie(response, AUTH_COOKIES.returnTo);
  }
  if (mode === "anonymous") {
    expireAuthCookie(response, AUTH_COOKIES.loginNotice);
  } else {
    response.cookies.set(AUTH_COOKIES.loginNotice, mode, authCookieOptions(120));
  }
  response.cookies.set(AUTH_COOKIES.loginChecked, "1", authCookieOptions(120));
  response.headers.set("cache-control", "no-store");
  return response;
}
