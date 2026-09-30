import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import OidcCallback from "@/components/OidcCallback";
import { AUTH_COOKIES, parseAuthFlow } from "@/lib/authState";
import { t } from "@/lib/i18n";

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
  const expectedState = cookieStore.get(AUTH_COOKIES.state)?.value;
  const flow = parseAuthFlow(cookieStore.get(AUTH_COOKIES.flow)?.value);
  const trustedState = typeof state === "string" && Boolean(state) && state === expectedState;

  if (typeof error === "string" && trustedState && error === "login_required" && flow === "silent") {
    redirect("/api/auth/login-recovery?mode=anonymous");
  }
  if (typeof error === "string" && trustedState && error === "access_denied" && (flow === "interactive" || flow === "session_expired")) {
    redirect("/api/auth/login-recovery?mode=login_cancelled");
  }
  if (error || typeof code !== "string" || !code || !trustedState || !flow) {
    redirect("/api/auth/callback-error");
  }

  return <OidcCallback code={code} state={state} loadingLabel={t("oidcCallbackLoading")} />;
}
