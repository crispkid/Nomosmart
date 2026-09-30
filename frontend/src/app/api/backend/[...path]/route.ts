import { NextRequest, NextResponse } from "next/server";
import { acquireUploadSlot, forwardUploadBody, isDocumentUpload, uploadProxyLimits, UploadProxyError } from "@/lib/uploadProxyStream";

export const runtime = "nodejs";

const hopByHopHeaders = new Set(["connection", "content-length", "host", "keep-alive", "transfer-encoding", "upgrade"]);

function backendBaseUrl() {
  return (process.env.BACKEND_INTERNAL_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const upstreamUrl = new URL(`${backendBaseUrl()}/${path.map(encodeURIComponent).join("/")}`);
  upstreamUrl.search = request.nextUrl.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!hopByHopHeaders.has(key.toLowerCase())) headers.set(key, value);
  });

  let release: (() => void) | undefined;
  let transfer: ReturnType<typeof forwardUploadBody> | undefined;
  try {
    if (isDocumentUpload(request.method, path)) {
      const limits = uploadProxyLimits();
      release = acquireUploadSlot(limits.inflight);
      if (!release) throw new UploadProxyError("upload_capacity_exhausted", 503);
      if (request.body) transfer = forwardUploadBody(request.body, request.signal, limits);
    }
    const options: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : transfer?.body ?? request.body,
      duplex: "half",
      signal: transfer?.signal ?? request.signal,
      cache: "no-store",
      redirect: "manual"
    };
    const upstream = await fetch(upstreamUrl, options);
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!hopByHopHeaders.has(key.toLowerCase())) responseHeaders.set(key, value);
    });
    responseHeaders.set("cache-control", "no-store");
    return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
  } catch (error) {
    const failure = transfer?.error() ?? (error instanceof UploadProxyError ? error : undefined);
    if (failure) {
      return NextResponse.json({ code: failure.code, message: "Upload request could not be completed", details: {}, request_id: crypto.randomUUID() }, {
        status: failure.status, headers: failure.code === "upload_capacity_exhausted" ? { "retry-after": "5", "cache-control": "no-store" } : { "cache-control": "no-store" },
      });
    }
    return NextResponse.json({ code: "backend_proxy_unreachable", message: "Backend API proxy failed to reach the upstream service" }, { status: 502 });
  } finally {
    transfer?.stop();
    release?.();
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
