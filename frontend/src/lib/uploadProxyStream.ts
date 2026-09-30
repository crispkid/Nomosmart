/** Bounded request forwarding. Never clone/tee/buffer a multipart body. */
export type UploadProxyLimits = { requestBytes: number; inflight: number; chunkBytes: number; idleMs: number; totalMs: number };

function integer(name: string, fallback: number, min: number, max: number): number {
  const value = process.env[name];
  if (value === undefined) return fallback;
  if (!/^\d+$/.test(value)) throw new Error("Invalid upload configuration");
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max) throw new Error("Invalid upload configuration");
  return parsed;
}

export function uploadProxyLimits(): UploadProxyLimits {
  const fileMiB = integer("NOMOSMART_DOCUMENT_MAX_UPLOAD_SIZE_MB", integer("MAX_UPLOAD_SIZE_MB", 100, 1, 10240), 1, 10240);
  const requestMiB = integer("DOCUMENT_UPLOAD_REQUEST_MAX_SIZE_MB", fileMiB + 1, fileMiB + 1, 10241);
  const idle = integer("NOMOSMART_UPLOAD_IDLE_TIMEOUT_SECONDS", 60, 5, 600);
  const total = integer("NOMOSMART_UPLOAD_TOTAL_TIMEOUT_SECONDS", 600, 10, 3600);
  if (total < idle) throw new Error("Invalid upload timeout configuration");
  return {
    requestBytes: requestMiB * 1024 * 1024,
    inflight: integer("NOMOSMART_UPLOAD_MAX_INFLIGHT", 2, 1, 16),
    chunkBytes: integer("NOMOSMART_UPLOAD_IO_CHUNK_KIB", 64, 4, 1024) * 1024,
    idleMs: idle * 1000, totalMs: total * 1000,
  };
}

export function isDocumentUpload(method: string, path: string[]): boolean {
  return method === "POST" && /^projects\/[^/]+\/documents\/(upload|[^/]+\/versions\/update-file)$/.test(path.join("/"));
}

let active = 0;
export function acquireUploadSlot(limit: number): (() => void) | undefined {
  if (active >= limit) return undefined;
  active++;
  let released = false;
  return () => { if (!released) { released = true; active--; } };
}

export class UploadProxyError extends Error {
  constructor(public code: string, public status: number) { super(code); }
}

export function forwardUploadBody(body: ReadableStream<Uint8Array>, signal: AbortSignal, limits: UploadProxyLimits) {
  const reader = body.getReader();
  const upstream = new AbortController();
  let failure: UploadProxyError | undefined;
  let stopped = false;
  let current: Uint8Array | undefined;
  let offset = 0;
  let count = 0;
  let idle: ReturnType<typeof setTimeout> | undefined;
  let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
  const fail = (error: UploadProxyError) => {
    if (stopped) return;
    failure = error;
    upstream.abort(error);
    streamController?.error(error);
    stop();
  };
  const resetIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(() => fail(new UploadProxyError("upload_receive_timeout", 408)), limits.idleMs);
  };
  const total = setTimeout(() => fail(new UploadProxyError("upload_receive_timeout", 408)), limits.totalMs);
  const cancel = () => fail(new UploadProxyError("upload_client_disconnected", 499));
  function stop() {
    if (stopped) return;
    stopped = true;
    current = undefined;
    clearTimeout(idle);
    clearTimeout(total);
    signal.removeEventListener("abort", cancel);
    // An early 401 must not wait for the client to finish sending a large file.
    void reader.cancel().catch(() => undefined).finally(() => reader.releaseLock());
  }
  const stream = new ReadableStream<Uint8Array>({
    start(controller) { streamController = controller; },
    async pull(controller) {
      if (stopped) { controller.close(); return; }
      try {
        if (!current || offset === current.byteLength) {
          resetIdle();
          const result = await reader.read();
          if (stopped) return;
          if (result.done) { clearTimeout(idle); controller.close(); return; }
          current = result.value;
          offset = 0;
          count += current.byteLength;
          if (count > limits.requestBytes) {
            fail(new UploadProxyError("upload_request_too_large", 413));
            return;
          }
        }
        const end = Math.min(current.byteLength, offset + limits.chunkBytes);
        controller.enqueue(current.slice(offset, end));
        offset = end;
        resetIdle();
      } catch {
        if (!stopped) fail(new UploadProxyError("upload_client_disconnected", 499));
      }
    },
    cancel() { stop(); },
  }, { highWaterMark: 0 });
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  return { body: stream, signal: upstream.signal, stop, error: () => failure };
}
