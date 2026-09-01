import { NextResponse } from "next/server";
import { AUTH_COOKIES, authCookieOptions, clearAuthorizationState } from "@/lib/authState";

export async function POST() {
  const response = NextResponse.json({ status: "cleared" });
  response.headers.set("cache-control", "no-store");
  clearAuthorizationState(response);
  response.cookies.set(AUTH_COOKIES.loginNotice, "logged_out", authCookieOptions(120));
  response.cookies.set(AUTH_COOKIES.loginChecked, "1", authCookieOptions(120));
  return response;
}
