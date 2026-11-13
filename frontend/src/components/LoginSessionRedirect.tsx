"use client";
import { useEffect } from "react";
import { useAuth } from "./AuthProvider";
import { safeReturnPath } from "@/lib/oidc";
export default function LoginSessionRedirect({ shouldProbe }: { shouldProbe: boolean }) {
  const { currentUser, authReady } = useAuth();
  useEffect(() => {
    if (authReady && currentUser && shouldProbe) window.location.replace(safeReturnPath(new URL(window.location.href).searchParams.get("returnTo") || "/"));
  }, [currentUser, authReady, shouldProbe]);
  return null;
}
