import { NextRequest } from "next/server";
import { createLoginRecoveryResponse, readAuthorizationOwner } from "@/lib/authState";

export async function GET(request: NextRequest) {
  const owner = await readAuthorizationOwner(request.cookies, request.nextUrl.searchParams.get("flow"));
  return createLoginRecoveryResponse(request, "oidc_error", null, owner);
}
