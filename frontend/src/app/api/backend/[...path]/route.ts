import { NextRequest, NextResponse } from "next/server";

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

  try {
    const upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual"
    });
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!hopByHopHeaders.has(key.toLowerCase())) responseHeaders.set(key, value);
    });
    responseHeaders.set("cache-control", "no-store");
    return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: responseHeaders });
  } catch {
    return NextResponse.json({ code: "backend_proxy_unreachable", message: "Backend API proxy failed to reach the upstream service" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
