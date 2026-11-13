/**
 * Framework-free read resource for keyed collections that cannot hold one React hook per key
 * (per-document pipeline observers, per-section system reads, cursor lists). Same rules as
 * useReadResource (OPT424-035): each read gets an AbortSignal; starting a newer read or
 * invalidating aborts the older one, whose result never commits; optional polling schedules the
 * next read after each current read and never overlaps a read.
 */
export type ReadOutcome<T> = { data: T } | { error: unknown };

export type ReadResourceControllerOptions<T> = {
  onStart?: () => void;
  onData?: (data: T) => void;
  onError?: (error: unknown) => void;
  /** After each current read, the delay in ms until the next read, or null to stop polling. */
  poll?: (outcome: ReadOutcome<T>) => number | null;
};

export class ReadResource<T> {
  private generation = 0;
  private controller: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inFlight = false;
  private last: ReadOutcome<T> | null = null;
  private lastLoad: ((signal: AbortSignal) => Promise<T>) | null = null;
  private disposed = false;
  private readonly options: ReadResourceControllerOptions<T>;

  constructor(options: ReadResourceControllerOptions<T> = {}) {
    this.options = options;
  }

  /** One read; resolves { committed } and rethrows the error of a current failed read. */
  async run(load: (signal: AbortSignal) => Promise<T>): Promise<{ committed: false } | { committed: true; data: T }> {
    if (this.disposed) return { committed: false };
    const request = ++this.generation;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.inFlight = true;
    this.lastLoad = load;
    this.options.onStart?.();
    let data: T;
    try {
      data = await load(controller.signal);
    } catch (error) {
      if (request !== this.generation) return { committed: false };
      this.inFlight = false;
      this.last = { error };
      this.options.onError?.(error);
      this.schedule();
      throw error;
    }
    if (request !== this.generation) return { committed: false };
    this.inFlight = false;
    this.last = { data };
    this.options.onData?.(data);
    this.schedule();
    return { committed: true, data };
  }

  /** run() without rethrowing; resolves whether the result committed. */
  async reload(load: (signal: AbortSignal) => Promise<T>): Promise<boolean> {
    try { return (await this.run(load)).committed; }
    catch { return false; }
  }

  /** Starts polling after `delay` ms with `load`, as if a read had just finished. */
  start(load: (signal: AbortSignal) => Promise<T>, delay: number): void {
    if (this.disposed) return;
    this.lastLoad = load;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.reload(load); }, delay);
  }

  /** Re-evaluates the polling delay (for example after a page visibility change). */
  schedule(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    const load = this.lastLoad;
    if (this.disposed || this.inFlight || !this.options.poll || !this.last || !load) return;
    const delay = this.options.poll(this.last);
    if (delay === null) return;
    this.timer = setTimeout(() => { void this.reload(load); }, delay);
  }

  /** Aborts the current read and any scheduled read; a later run() starts afresh. */
  invalidate(): void {
    this.generation += 1;
    this.controller?.abort();
    this.controller = null;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.inFlight = false;
    this.last = null;
  }

  /** invalidate() and refuse further reads. */
  dispose(): void {
    this.invalidate();
    this.disposed = true;
  }
}
