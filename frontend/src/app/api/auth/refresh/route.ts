import { NextRequest, NextResponse } from "next/server";
import { oidcConfig } from "@/lib/oidc";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({})) as { refreshToken?: string };
  if (!body.refreshToken) return NextResponse.json({ code: "refresh_token_required" }, { status: 400 });
  const config = oidcConfig();
  const upstream = await fetch(`${config.internalIssuer}/protocol/openid-connect/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ grant_type: "refresh_token", client_id: config.clientId, refresh_token: body.refreshToken }), cache: "no-store" });
  if (!upstream.ok) return NextResponse.json({ code: "oidc_refresh_failed" }, { status: 401 });
  const tokens = await upstream.json() as { access_token?: string; refresh_token?: string; id_token?: string; expires_in?: number };
  if (!tokens.access_token || !tokens.refresh_token) return NextResponse.json({ code: "oidc_token_invalid" }, { status: 401 });
  const response = NextResponse.json({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token, idToken: tokens.id_token, expiresIn: tokens.expires_in ?? 300 }); response.headers.set("cache-control", "no-store"); return response;
}
