import type { OidcTokens } from "./oidc";

type RecoveryMode = "auth_service_unavailable" | "oidc_error";
type Result = { kind: "success"; tokens: OidcTokens; returnTo: string } | { kind: "failure"; mode: RecoveryMode };
export type CallbackSubscriber = {
  accepts: () => boolean;
  success: (tokens: OidcTokens, returnTo: string) => void;
  failure: (mode: RecoveryMode) => void;
};
type Lease = { active: boolean; order: number; subscriber: CallbackSubscriber };
type Work = {
  key: string;
  generation: number;
  controller: AbortController;
  timer: ReturnType<typeof setTimeout>;
  terminal: boolean;
  result: Result | null;
  leases: Set<Lease>;
};

/** One callback transaction per Provider; credentials and identities never leave memory. */
export class OidcCallbackFlow {
  private work: Work | null = null;
  private owners = 0;
  private disposed = false;
  private pending = new Set<Lease>();
  private order = 0;

  retain(): () => void {
    this.owners += 1;
    let retained = true;
    return () => {
      if (!retained) return;
      retained = false;
      this.owners -= 1;
      // Strict Mode reacquires ownership synchronously before this microtask.
      queueMicrotask(() => { if (this.owners === 0) this.dispose(); });
    };
  }

  subscribe(code: string, state: string, generation: number, subscriber: CallbackSubscriber): () => void {
    const lease: Lease = { active: true, order: ++this.order, subscriber };
    this.pending.add(lease);
    void this.attach(code, state, generation, lease);
    return () => {
      lease.active = false;
      this.pending.delete(lease);
      this.work?.leases.delete(lease);
    };
  }

  invalidate(): void {
    for (const lease of this.pending) lease.active = false;
    this.pending.clear();
    const work = this.work;
    if (!work) return;
    work.terminal = true;
    work.result = null;
    work.leases.clear();
    clearTimeout(work.timer);
    work.controller.abort();
  }

  private dispose(): void {
    this.disposed = true;
    this.invalidate();
    this.work = null;
  }

  private async attach(code: string, state: string, generation: number, lease: Lease): Promise<void> {
    try {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([code, state])));
      this.pending.delete(lease);
      if (this.disposed || !lease.active || lease.order !== this.order || !lease.subscriber.accepts()) return;
      const key = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
      if (this.work?.key === key) {
        if (this.work.terminal) return;
        if (this.work.generation !== generation) { this.invalidate(); return; }
        this.work.leases.add(lease);
        this.deliver(this.work);
        return;
      }
      this.invalidate();
      const controller = new AbortController();
      const work: Work = {
        key, generation, controller, terminal: false, result: null, leases: new Set([lease]),
        timer: setTimeout(() => {
          if (this.work !== work || work.terminal) return;
          controller.abort();
          work.result = { kind: "failure", mode: "auth_service_unavailable" };
          this.deliver(work);
        }, 8000),
      };
      this.work = work;
      void this.exchange(work, code, state);
    } catch {
      this.pending.delete(lease);
      if (!this.disposed && lease.active && lease.order === this.order && lease.subscriber.accepts()) {
        lease.active = false;
        lease.subscriber.failure("auth_service_unavailable");
      }
    }
  }

  private settle(work: Work, result: Result): void {
    if (this.work !== work || work.terminal || work.controller.signal.aborted) return;
    work.result = result;
    this.deliver(work);
  }

  private deliver(work: Work): void {
    if (this.work !== work || work.terminal || !work.result) return;
    const lease = [...work.leases].find((candidate) => candidate.active && candidate.order === this.order && candidate.subscriber.accepts());
    if (!lease) return;
    const result = work.result;
    work.terminal = true;
    work.result = null;
    work.leases.clear();
    clearTimeout(work.timer);
    lease.active = false;
    if (result.kind === "success") lease.subscriber.success(result.tokens, result.returnTo);
    else lease.subscriber.failure(result.mode);
  }

  private async exchange(work: Work, code: string, state: string): Promise<void> {
    try {
      const response = await fetch("/api/auth/exchange", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ code, state }), cache: "no-store", signal: work.controller.signal,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { code?: string };
        this.settle(work, { kind: "failure", mode: response.status === 503 || body.code === "oidc_service_unavailable" ? "auth_service_unavailable" : "oidc_error" });
        return;
      }
      const body = await response.json() as { accessToken: string; refreshToken: string; idToken?: string; expiresIn: number; returnTo: string };
      if (!body || typeof body.accessToken !== "string" || !body.accessToken || typeof body.refreshToken !== "string" || !body.refreshToken
        || !Number.isFinite(body.expiresIn) || body.expiresIn <= 0 || typeof body.returnTo !== "string") {
        this.settle(work, { kind: "failure", mode: "oidc_error" });
        return;
      }
      this.settle(work, { kind: "success", tokens: { accessToken: body.accessToken, refreshToken: body.refreshToken, idToken: body.idToken, expiresAt: Date.now() + body.expiresIn * 1000 }, returnTo: body.returnTo });
    } catch {
      this.settle(work, { kind: "failure", mode: "auth_service_unavailable" });
    }
  }
}
