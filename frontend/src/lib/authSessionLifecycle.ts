

/** Never include credentials, provider response bodies or request URLs. */
export class RefreshFailure extends Error {
  readonly kind: "expired" | "unavailable";
  constructor(kind: "expired" | "unavailable") {
    super(kind === "expired" ? "oidc_refresh_failed" : "oidc_service_unavailable");
    this.kind = kind;
    this.name = "RefreshFailure";
  }
}

export function refreshFailureForStatus(status: number): RefreshFailure {
  return new RefreshFailure(status === 400 || status === 401 || status === 403 ? "expired" : "unavailable");
}

/** Shared by browser runtime configuration and the server-side refresh transport. */
export function authLogoutTimeout(value: unknown = undefined): number {
  if (value === undefined) return 10_000;
  if (typeof value !== "number" && (typeof value !== "string" || !/^\d+$/.test(value))) {
    throw new Error("invalid_auth_logout_timeout");
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 2_000 || parsed > 30_000) throw new Error("invalid_auth_logout_timeout");
  return parsed;
}

