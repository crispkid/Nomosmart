"use client";

import { useEffect, useRef } from "react";
import { useAuth } from "@/components/AuthProvider";

export default function LoginSessionRedirect({ shouldProbe }: { shouldProbe: boolean }) {
  const { tokens, currentUser } = useAuth();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    if (tokens && currentUser) {
      started.current = true;
      window.location.replace("/api/auth/continue");
      return;
    }
    if (shouldProbe && !tokens) {
      started.current = true;
      window.location.replace("/api/auth/start?prompt=none");
    }
  }, [currentUser, shouldProbe, tokens]);

  return null;
}
