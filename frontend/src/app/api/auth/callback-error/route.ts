import { NextRequest } from "next/server";
import { createLoginRecoveryResponse } from "@/lib/authState";

export async function GET(request: NextRequest) {
  return createLoginRecoveryResponse(request, "oidc_error");
}
