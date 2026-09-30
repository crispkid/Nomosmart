import { NextRequest, NextResponse } from "next/server";
import { oidcConfig } from "@/lib/oidc";
import { authLogoutTimeout } from "@/lib/authSessionLifecycle";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null) as { refreshToken?: string } | null;
  if (typeof body?.refreshToken !== "string" || !body.refreshToken) return NextResponse.json({ code: "refresh_token_required" }, { status: 400, headers: { "cache-control": "no-store" } });
  const config = oidcConfig();
  const timeout = authLogoutTimeout(process.env.FRONTEND_AUTH_LOGOUT_TIMEOUT_MS);
  try {
  const upstream = await fetch(`${config.internalIssuer}/protocol/openid-connect/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ grant_type: "refresh_token", client_id: config.clientId, refresh_token: body.refreshToken }), cache: "no-store", signal: AbortSignal.any([request.signal, AbortSignal.timeout(timeout)]) });
  if (upstream.status >= 500) return NextResponse.json({ code: "oidc_service_unavailable" }, { status: 503, headers: { "cache-control": "no-store" } });
  if (!upstream.ok) return NextResponse.json({ code: "oidc_refresh_failed" }, { status: 401, headers: { "cache-control": "no-store" } });
  const tokens = await upstream.json() as { access_token?: string; refresh_token?: string; id_token?: string; expires_in?: number };
  if (!tokens.access_token || !tokens.refresh_token) return NextResponse.json({ code: "oidc_token_invalid" }, { status: 401 });
  const response = NextResponse.json({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, idToken: tokens.id_token, expiresIn: tokens.expires_in ?? 300 }); response.headers.set("cache-control", "no-store"); return response;
  } catch {
    return NextResponse.json({ code: "oidc_service_unavailable" }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
