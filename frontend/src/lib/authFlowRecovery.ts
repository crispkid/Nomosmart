import type { LoginRecoveryMode } from "./authState";

export function parseAuthFlowId(value: unknown): string | null {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : null;
}

export function loginRecoveryPath(mode: LoginRecoveryMode, flowId?: string | null): string {
  const params = new URLSearchParams({ mode });
  const owner = parseAuthFlowId(flowId);
  if (owner) params.set("flow", owner);
  return `/api/auth/login-recovery?${params}`;
}
