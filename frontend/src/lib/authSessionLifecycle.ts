import type { OidcTokens } from "./oidc";

export type LogoutOutcome = "confirmed" | "unconfirmed";
export type LogoutResult = { outcome: LogoutOutcome; cleanupConfirmed: boolean };

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

type RefreshWork = { controller: AbortController; promise: Promise<OidcTokens> };
type LogoutOptions = { refreshUrl: string; revokeUrl: string; cleanupUrl: string; timeoutMs: number };

/** Owns credentials in memory only. A terminal transition never installs late results. */
export class AuthSessionLifecycle {
  private epoch = 0;
  private closing = false;
  private tokens: OidcTokens | null = null;
  private refreshWork: RefreshWork | null = null;
  private logoutWork: Promise<LogoutResult> | null = null;

  generation(): number { return this.epoch; }
  accepts(generation: number): boolean { return !this.closing && generation === this.epoch; }
  isClosing(): boolean { return this.closing; }
  current(): OidcTokens | null { return this.closing ? null : this.tokens; }
  assertActive(generation: number): void {
    if (!this.accepts(generation)) throw new Error("auth_transition_superseded");
  }
  install(tokens: OidcTokens): void {
    this.assertActive(this.epoch);
    this.refreshWork?.controller.abort();
    this.refreshWork = null;
    this.epoch += 1;
    this.tokens = tokens;
  }
  invalidate(): void {
    this.closing = true;
    this.epoch += 1;
    this.tokens = null;
    this.refreshWork?.controller.abort();
  }

  private startRefresh(tokens: OidcTokens, url: string, timeoutMs: number): RefreshWork {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const generation = this.epoch;
    const promise = (async () => {
      const response = await fetch(url, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ refreshToken: tokens.refreshToken }), cache: "no-store", signal: controller.signal,
      }).catch(() => { throw new RefreshFailure("unavailable"); });
      if (!response.ok) throw refreshFailureForStatus(response.status);
      const body = await response.json().catch(() => { throw new RefreshFailure("unavailable"); }) as Partial<{ accessToken: string; refreshToken: string; idToken: string; expiresIn: number }> | null;
      if (!body || typeof body.accessToken !== "string" || !body.accessToken || typeof body.refreshToken !== "string"
        || !body.refreshToken || !Number.isFinite(body.expiresIn) || body.expiresIn! <= 0) {
        throw new RefreshFailure("expired");
      }
      const next: OidcTokens = {
        accessToken: body.accessToken, refreshToken: body.refreshToken,
        idToken: body.idToken ?? tokens.idToken, expiresAt: Date.now() + body.expiresIn! * 1000,
      };
      if (this.accepts(generation)) this.tokens = next;
      return next;
    })().finally(() => {
      clearTimeout(timer);
      if (this.refreshWork?.controller === controller) this.refreshWork = null;
    });
    this.refreshWork = { controller, promise };
    return this.refreshWork;
  }

  async refresh(generation: number, url: string, timeoutMs: number, rejectedToken?: string): Promise<OidcTokens> {
    this.assertActive(generation);
    const current = this.tokens;
    if (!current) throw new Error("authentication_required");
    // An older concurrent request must not rotate the replacement a second time.
    if (rejectedToken && current.accessToken !== rejectedToken) return current;
    const next = await (this.refreshWork ?? this.startRefresh(current, url, timeoutMs)).promise;
    this.assertActive(generation);
    return next;
  }

  logout(options: LogoutOptions): Promise<LogoutResult> {
    if (this.logoutWork) return this.logoutWork;
    const original = this.tokens;
    const pending = this.refreshWork;
    this.closing = true;
    this.epoch += 1;
    this.tokens = null;
    this.logoutWork = this.finishLogout(original, pending, options);
    return this.logoutWork;
  }

  private async finishLogout(original: OidcTokens | null, pending: RefreshWork | null, options: LogoutOptions): Promise<LogoutResult> {
    const deadline = Date.now() + options.timeoutMs;
    const revokeDeadline = deadline - Math.min(2000, options.timeoutMs / 4);
    const candidates = original ? [original] : [];
    const statuses = new Map<string, number>();
    let refreshUsed = false;
    let uncertain = false;
    let attempts = 0;
    const remaining = () => Math.max(1, revokeDeadline - Date.now());
    const takeRefresh = async () => {
      if (refreshUsed || !original || Date.now() >= revokeDeadline) { uncertain = true; return; }
      refreshUsed = true;
      const work = pending ?? this.startRefresh(original, options.refreshUrl, remaining());
      const timer = setTimeout(() => work.controller.abort(), remaining());
      try {
        const next = await work.promise;
        if (!candidates.some((item) => item.accessToken === next.accessToken)) candidates.push(next);
      } catch { uncertain = true; }
      finally { clearTimeout(timer); }
    };
    const revoke = async (current: OidcTokens) => {
      if (Date.now() >= revokeDeadline || attempts >= 3) { uncertain = true; return; }
      attempts += 1;
      try {
        const response = await fetch(options.revokeUrl, {
          method: "POST", headers: { Authorization: `Bearer ${current.accessToken}` },
          cache: "no-store", signal: AbortSignal.timeout(remaining()),
        });
        statuses.set(current.accessToken, response.status);
      } catch { uncertain = true; statuses.set(current.accessToken, 0); }
    };
    try {
      if (pending || (original && original.expiresAt <= Date.now())) await takeRefresh();
      for (let index = 0; index < candidates.length; index += 1) {
        const current = candidates[index];
        if (current.expiresAt <= Date.now()) continue;
        await revoke(current);
        if (statuses.get(current.accessToken) === 401 && !refreshUsed) await takeRefresh();
      }
      // One bounded retry for an original credential rejected during a concurrent refresh.
      if (refreshUsed && original && statuses.get(original.accessToken) === 401 && original.expiresAt > Date.now()) {
        await revoke(original);
      }
    } catch { uncertain = true; }
    finally {
      this.refreshWork?.controller.abort();
      this.refreshWork = null;
    }
    const succeeded = [...statuses.values()].some((status) => status >= 200 && status < 300);
    const unresolved = candidates.some((item) => item.expiresAt > Date.now() &&
      !((statuses.get(item.accessToken) ?? 0) >= 200 && (statuses.get(item.accessToken) ?? 0) < 300));
    const outcome: LogoutOutcome = succeeded && !uncertain && !unresolved ? "confirmed" : "unconfirmed";
    // Credentials never escape in the retained result or diagnostics.
    candidates.length = 0;
    statuses.clear();
    try {
      const response = await fetch(options.cleanupUrl, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ outcome }),
        cache: "no-store", signal: AbortSignal.timeout(Math.max(1, deadline - Date.now())),
      });
      return { outcome: response.ok ? outcome : "unconfirmed", cleanupConfirmed: response.ok };
    } catch { return { outcome: "unconfirmed", cleanupConfirmed: false }; }
  }
}
