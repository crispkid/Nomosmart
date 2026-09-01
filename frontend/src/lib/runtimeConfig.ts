export type RuntimeConfig = {
  appOrigin: string;
  apiBaseUrl: string;
  oidcIssuerUrl: string;
  oidcClientId: string;
  oidcAudience: string;
};

declare global {
  interface Window {
    __NOMOSMART_RUNTIME_CONFIG__?: RuntimeConfig;
  }
}

const defaults: RuntimeConfig = {
  appOrigin: "http://127.0.0.1:3000",
  apiBaseUrl: "/api/backend",
  oidcIssuerUrl: "http://127.0.0.1:8080/realms/nomosmart",
  oidcClientId: "nomosmart-frontend",
  oidcAudience: "nomosmart-backend",
};

export function runtimeConfig(): RuntimeConfig {
  if (typeof window !== "undefined" && window.__NOMOSMART_RUNTIME_CONFIG__) {
    return window.__NOMOSMART_RUNTIME_CONFIG__;
  }
  return defaults;
}
