import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIES, authCookieOptions, clearAuthorizationState } from "@/lib/authState";

export async function POST(request: NextRequest) {
  const body: unknown = await request.json().catch(() => null);
  const confirmed = body !== null && typeof body === "object" && "outcome" in body && body.outcome === "confirmed";
  const response = NextResponse.json({ status: "cleared" });
  response.headers.set("cache-control", "no-store");
  clearAuthorizationState(response);
  response.cookies.set(AUTH_COOKIES.loginNotice, confirmed ? "logged_out" : "logout_incomplete", authCookieOptions(120));
  response.cookies.set(AUTH_COOKIES.loginChecked, "1", authCookieOptions(120));
  return response;
}
