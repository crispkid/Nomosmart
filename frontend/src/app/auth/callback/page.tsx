import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import OidcCallback from "@/components/OidcCallback";
import { AUTH_FLOW_COOKIE_PREFIX, readAuthorizationState } from "@/lib/authState";
import { loginRecoveryPath } from "@/lib/authFlowRecovery";

type OidcCallbackPageProps = {
  searchParams: Promise<{
    code?: string | string[];
    error?: string | string[];
    state?: string | string[];
  }>;
};

export default async function OidcCallbackPage({ searchParams }: OidcCallbackPageProps) {
  const { code, error, state } = await searchParams;
  const cookieStore = await cookies();
  const owner = await readAuthorizationState(cookieStore, state);
  const flow = owner?.packet.flow;
  const flowId = owner?.name.slice(AUTH_FLOW_COOKIE_PREFIX.length);
  const trustedState = Boolean(owner);

  if (typeof error === "string" && trustedState && error === "login_required" && flow === "silent") {
    redirect(loginRecoveryPath("anonymous", flowId));
  }
  if (typeof error === "string" && trustedState && error === "access_denied" && (flow === "interactive" || flow === "session_expired")) {
    redirect(loginRecoveryPath("login_cancelled", flowId));
  }
  if (error || typeof code !== "string" || !code || typeof state !== "string" || !trustedState || !flow || !flowId) {
    redirect(flowId ? `/api/auth/callback-error?flow=${flowId}` : "/api/auth/callback-error");
  }

  return <OidcCallback code={code} state={state} flowId={flowId} />;
}
