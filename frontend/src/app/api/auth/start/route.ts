import { NextRequest, NextResponse } from "next/server";
import { safeReturnPath } from "@/lib/oidc";

export async function GET(request: NextRequest) {
  const origin = (process.env.FRONTEND_APP_ORIGIN || request.nextUrl.origin).replace(/\/$/, "");
  const base = (process.env.BACKEND_INTERNAL_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
  const returnTo = safeReturnPath(request.nextUrl.searchParams.get("returnTo"));
  try {
    const upstream = await fetch(`${base}/auth/oidc/start`, { method: "POST", headers: { "Content-Type": "application/json", Origin: origin, Cookie: request.headers.get("cookie") || "" }, body: JSON.stringify({ return_to: returnTo }), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15000) });
    if (!upstream.ok) throw new Error("oidc_start_failed");
    const result = await upstream.json() as { authorization_url: string };
    const url = new URL(result.authorization_url);
    if (url.protocol !== "https:") throw new Error("oidc_transport_invalid");
    const response = NextResponse.redirect(url, 303);
    for (const cookie of upstream.headers.getSetCookie()) response.headers.append("set-cookie", cookie);
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch {
    return NextResponse.redirect(new URL(`/login?notice=auth_service_unavailable&returnTo=${encodeURIComponent(returnTo)}`, origin), 303);
  }
}
