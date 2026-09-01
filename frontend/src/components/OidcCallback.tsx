"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

export default function OidcCallback({ code, state, loadingLabel }: { code: string; state: string; loadingLabel: string }) {
  const router = useRouter(); const { installTokens } = useAuth();
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      controller.abort();
      window.location.replace("/api/auth/login-recovery?mode=auth_service_unavailable");
    }, 8000);
    fetch("/api/auth/exchange", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code, state }), cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { code?: string };
        const mode = response.status === 503 || body.code === "oidc_service_unavailable" ? "auth_service_unavailable" : "oidc_error";
        window.location.replace(`/api/auth/login-recovery?mode=${mode}`);
        return;
      }
      const body = await response.json() as { accessToken: string; refreshToken: string; idToken?: string; expiresIn: number; returnTo: string };
      installTokens({ accessToken: body.accessToken, refreshToken: body.refreshToken, idToken: body.idToken, expiresAt: Date.now() + body.expiresIn * 1000 }); window.history.replaceState(null, "", "/auth/callback"); router.replace(body.returnTo);
    }).catch((reason: unknown) => { if ((reason as Error).name !== "AbortError") window.location.replace("/api/auth/login-recovery?mode=auth_service_unavailable"); }).finally(() => window.clearTimeout(timeout));
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [code, installTokens, router, state]);
  return <main className="auth-loading" role="status">{loadingLabel}</main>;
}
