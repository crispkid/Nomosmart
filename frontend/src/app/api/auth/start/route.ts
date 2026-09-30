import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIES, authCookieOptions, createLoginRecoveryResponse, parseLoginNotice, type AuthFlow } from "@/lib/authState";
import { authorizationUrl, oidcConfig, pkceChallenge, randomUrlToken, safeReturnPath } from "@/lib/oidc";

export async function GET(request: NextRequest) {
  const verifier = randomUrlToken(48), state = randomUrlToken(), nonce = randomUrlToken();
  const prompt = request.nextUrl.searchParams.get("prompt") === "none" ? "none" : undefined;
  const priorNotice = parseLoginNotice(request.cookies.get(AUTH_COOKIES.loginNotice)?.value);
  const flow: AuthFlow = prompt === "none" ? "silent" : priorNotice === "session_expired" ? "session_expired" : "interactive";
  const returnTo = safeReturnPath(request.nextUrl.searchParams.get("returnTo") ?? request.cookies.get(AUTH_COOKIES.returnTo)?.value);
  const config = oidcConfig();
  try {
    const discovery = await fetch(`${config.internalIssuer}/.well-known/openid-configuration`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    if (!discovery.ok) throw new Error("oidc_discovery_unavailable");
  } catch {
    return createLoginRecoveryResponse(request, "auth_service_unavailable", returnTo);
  }
  const response = NextResponse.redirect(authorizationUrl(config, { state, nonce, challenge: await pkceChallenge(verifier), prompt }));
  const options = authCookieOptions();
  response.cookies.set(AUTH_COOKIES.pkce, verifier, options);
  response.cookies.set(AUTH_COOKIES.state, state, options);
  response.cookies.set(AUTH_COOKIES.nonce, nonce, options);
  response.cookies.set(AUTH_COOKIES.flow, flow, options);
  response.cookies.set(AUTH_COOKIES.returnTo, returnTo, options);
  if (flow !== "silent") {
    response.cookies.delete(AUTH_COOKIES.loginNotice);
    response.cookies.delete(AUTH_COOKIES.loginChecked);
  }
  return response;
}
