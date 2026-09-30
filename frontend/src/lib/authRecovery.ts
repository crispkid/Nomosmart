/** One automatic probe per recovery entry; manual/online requests share actual IO. */
export class AuthRecoveryProbe {
  private automaticUsed = false;
  private stopped = false;
  private verified = false;
  private work: { controller: AbortController; promise: Promise<boolean> } | null = null;

  start(automatic: boolean, url: string, timeoutMs: number): Promise<boolean> | null {
    if (this.stopped || this.verified) return null;
    if (this.work) return this.work.promise;
    if (automatic && this.automaticUsed) return null;
    // A manual attempt also consumes the automatic allowance, so an online
    // event cannot launch another navigation immediately after its failure.
    this.automaticUsed = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const promise = fetch(url, { cache: "no-store", credentials: "omit", signal: controller.signal })
      .then((response) => {
        const verified = response.ok && !response.redirected && !controller.signal.aborted && !this.stopped;
        if (verified) this.verified = true;
        return verified;
      }).catch(() => false).finally(() => {
        clearTimeout(timer);
        if (this.work?.controller === controller) this.work = null;
      });
    this.work = { controller, promise };
    return promise;
  }

  stop(): void { this.stopped = true; this.work?.controller.abort(); }
}
