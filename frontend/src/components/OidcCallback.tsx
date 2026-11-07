"use client";
import { useEffect } from "react";
export default function OidcCallback(_props: { code?: string; state?: string; flowId?: string }) {
  useEffect(() => { window.location.replace("/login?notice=oidc_error"); }, []);
  return null;
}
