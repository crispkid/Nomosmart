import { NextRequest, NextResponse } from "next/server";
import { clearAuthorizationState, readAuthorizationState } from "@/lib/authState";
import { decodeJwtPayload, oidcConfig } from "@/lib/oidc";

export async function POST(request: NextRequest) {
  const input: unknown = await request.json().catch(() => null);
  const body = input && typeof input === "object" && !Array.isArray(input) ? input as Record<string, unknown> : {};
  const owner = await readAuthorizationState(request.cookies, body.state);
  const reject = (code: string, status: number) => {
    const response = NextResponse.json({ code }, { status });
    response.headers.set("cache-control", "no-store");
    clearAuthorizationState(response, owner);
    return response;
  };
  if (typeof body.code !== "string" || !body.code || !owner) return reject("oidc_state_invalid", 400);
  const config = oidcConfig();
  let upstream: Response;
  try {
    upstream = await fetch(`${config.internalIssuer}/protocol/openid-connect/token`, {
      method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "authorization_code", client_id: config.clientId, redirect_uri: config.callbackUrl, code: body.code, code_verifier: owner.packet.verifier }),
      cache: "no-store", signal: AbortSignal.timeout(5000),
    });
  } catch {
    return reject("oidc_service_unavailable", 503);
  }
  if (!upstream.ok) return reject("oidc_exchange_failed", 401);
  try {
    const tokens: unknown = await upstream.json();
    if (!tokens || typeof tokens !== "object" || Array.isArray(tokens)) return reject("oidc_token_invalid", 401);
    const data = tokens as Record<string, unknown>;
    if (typeof data.access_token !== "string" || !data.access_token || typeof data.refresh_token !== "string" || !data.refresh_token
      || typeof data.id_token !== "string" || !data.id_token || decodeJwtPayload(data.id_token).nonce !== owner.packet.nonce) return reject("oidc_token_invalid", 401);
    const response = NextResponse.json({ accessToken: data.access_token, refreshToken: data.refresh_token, idToken: data.id_token, expiresIn: data.expires_in ?? 300, returnTo: owner.packet.returnTo });
    response.headers.set("cache-control", "no-store");
    clearAuthorizationState(response, owner);
    return response;
  } catch {
    return reject("oidc_token_invalid", 401);
  }
}
