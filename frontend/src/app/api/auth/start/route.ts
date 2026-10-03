import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIES, AUTH_FLOW_COOKIE_PREFIX, AUTH_FLOW_LIMIT, AUTH_FLOW_TTL_SECONDS, authCookieOptions, authorizationFlowId, boundedReturnPath, clearLegacyAuthorizationState, createLoginRecoveryResponse, encodeAuthorizationPacket, expireAuthCookie, inspectAuthorizationStates, parseLoginNotice, type AuthFlow, type AuthorizationPacket } from "@/lib/authState";
import { authorizationUrl, oidcConfig, pkceChallenge, randomUrlToken } from "@/lib/oidc";

export async function GET(request: NextRequest) {
  const inventory = await inspectAuthorizationStates(request.cookies);
  const cleanObsolete = (response: NextResponse) => {
    for (const name of inventory.obsoleteNames) expireAuthCookie(response, name);
    return response;
  };
  if (inventory.active.length >= AUTH_FLOW_LIMIT) return cleanObsolete(createLoginRecoveryResponse(request, "auth_service_unavailable"));
  const verifier = randomUrlToken(48), state = randomUrlToken(), nonce = randomUrlToken();
  const prompt = request.nextUrl.searchParams.get("prompt") === "none" ? "none" : undefined;
  const priorNotice = parseLoginNotice(request.cookies.get(AUTH_COOKIES.loginNotice)?.value);
  const flow: AuthFlow = prompt === "none" ? "silent" : priorNotice === "session_expired" ? "session_expired" : "interactive";
  const returnTo = boundedReturnPath(request.nextUrl.searchParams.get("returnTo") ?? request.cookies.get(AUTH_COOKIES.returnTo)?.value);
  const config = oidcConfig();
  try {
    const discovery = await fetch(`${config.internalIssuer}/.well-known/openid-configuration`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!discovery.ok) throw new Error("oidc_discovery_unavailable");
  } catch {
    return cleanObsolete(createLoginRecoveryResponse(request, "auth_service_unavailable", returnTo));
  }
  const response = NextResponse.redirect(authorizationUrl(config, { state, nonce, challenge: await pkceChallenge(verifier), prompt }));
  const createdAt = Date.now();
  const packet: AuthorizationPacket = { version: 2, state, verifier, nonce, flow, returnTo, createdAt, expiresAt: createdAt + AUTH_FLOW_TTL_SECONDS * 1000 };
  let encoded: string;
  try { encoded = encodeAuthorizationPacket(packet); }
  catch { packet.returnTo = "/"; encoded = encodeAuthorizationPacket(packet); }
  response.cookies.set(AUTH_FLOW_COOKIE_PREFIX + await authorizationFlowId(state), encoded, { ...authCookieOptions(AUTH_FLOW_TTL_SECONDS), expires: new Date(packet.expiresAt) });
  clearLegacyAuthorizationState(response);
  expireAuthCookie(response, AUTH_COOKIES.returnTo);
  if (flow !== "silent") {
    expireAuthCookie(response, AUTH_COOKIES.loginNotice);
    expireAuthCookie(response, AUTH_COOKIES.loginChecked);
  }
  response.headers.set("cache-control", "no-store");
  return cleanObsolete(response);
}
