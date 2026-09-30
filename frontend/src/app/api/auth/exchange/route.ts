import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIES, clearAuthorizationState } from "@/lib/authState";
import { decodeJwtPayload, oidcConfig, safeReturnPath } from "@/lib/oidc";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({})) as { code?: string; state?: string };
  const verifier = request.cookies.get(AUTH_COOKIES.pkce)?.value, state = request.cookies.get(AUTH_COOKIES.state)?.value, nonce = request.cookies.get(AUTH_COOKIES.nonce)?.value;
  if (!body.code || !body.state || !verifier || !state || body.state !== state) { const response = NextResponse.json({ code: "oidc_state_invalid" }, { status: 400 }); clearAuthorizationState(response); return response; }
  const config = oidcConfig();
  let upstream: Response;
  try {
    upstream = await fetch(`${config.internalIssuer}/protocol/openid-connect/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ grant_type: "authorization_code", client_id: config.clientId, redirect_uri: config.callbackUrl, code: body.code, code_verifier: verifier }), cache: "no-store", signal: AbortSignal.timeout(5000) });
  } catch {
    const response = NextResponse.json({ code: "oidc_service_unavailable" }, { status: 503 });
    clearAuthorizationState(response);
    return response;
  }
  if (!upstream.ok) { const response = NextResponse.json({ code: "oidc_exchange_failed" }, { status: 401 }); clearAuthorizationState(response); return response; }
  const tokens = await upstream.json() as { access_token?: string; refresh_token?: string; id_token?: string; expires_in?: number };
  if (!tokens.access_token || !tokens.refresh_token || !tokens.id_token || decodeJwtPayload(tokens.id_token).nonce !== nonce) { const response = NextResponse.json({ code: "oidc_token_invalid" }, { status: 401 }); clearAuthorizationState(response); return response; }
  const response = NextResponse.json({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, idToken: tokens.id_token, expiresIn: tokens.expires_in ?? 300, returnTo: safeReturnPath(request.cookies.get(AUTH_COOKIES.returnTo)?.value) });
  response.headers.set("cache-control", "no-store"); clearAuthorizationState(response); return response;
}
