import { NextRequest } from "next/server";
import { createLoginRecoveryResponse, parseLoginRecoveryMode } from "@/lib/authState";

export async function GET(request: NextRequest) {
  const mode = parseLoginRecoveryMode(request.nextUrl.searchParams.get("mode"));
  return createLoginRecoveryResponse(request, mode, request.nextUrl.searchParams.get("returnTo"));
}
