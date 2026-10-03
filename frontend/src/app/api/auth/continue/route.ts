import { NextRequest, NextResponse } from "next/server";
import { AUTH_COOKIES, clearLoginFlash } from "@/lib/authState";
import { safeReturnPath } from "@/lib/oidc";

export async function GET(request: NextRequest) {
  const returnTo = safeReturnPath(request.cookies.get(AUTH_COOKIES.returnTo)?.value);
  const response = NextResponse.redirect(new URL(returnTo, request.nextUrl.origin));
  clearLoginFlash(response);
  response.headers.set("cache-control", "no-store");
  return response;
}
