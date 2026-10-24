import type { NextConfig } from "next";

function allowedDevOrigins() {
  const configured = process.env.FRONTEND_ALLOWED_DEV_ORIGINS
    ?.split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  if (configured?.length) return configured;
  try {
    const appOrigin = process.env.FRONTEND_APP_ORIGIN ?? process.env.NEXT_PUBLIC_APP_ORIGIN ?? "http://127.0.0.1:3000";
    return [new URL(appOrigin).hostname];
  } catch {
    return [];
  }
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  typescript: {
    tsconfigPath: process.env.NODE_ENV === "development" ? "tsconfig.dev.json" : "tsconfig.json"
  },
  allowedDevOrigins: allowedDevOrigins()
};

export default nextConfig;
