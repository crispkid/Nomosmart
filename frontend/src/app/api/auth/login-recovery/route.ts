import { NextRequest } from "next/server";
import { createLoginRecoveryResponse, parseLoginRecoveryMode, readAuthorizationOwner } from "@/lib/authState";

export async function GET(request: NextRequest) {
  const mode = parseLoginRecoveryMode(request.nextUrl.searchParams.get("mode"));
  const owner = await readAuthorizationOwner(request.cookies, request.nextUrl.searchParams.get("flow"));
  return createLoginRecoveryResponse(request, mode, request.nextUrl.searchParams.get("returnTo"), owner);
}
