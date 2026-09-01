import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const authProvider = readFileSync(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8");
const deniedComponent = readFileSync(new URL("../src/components/ApplicationAccessDenied.tsx", import.meta.url), "utf8");
const deniedRoute = readFileSync(new URL("../src/app/access-denied/page.tsx", import.meta.url), "utf8");
const layout = readFileSync(new URL("../src/app/layout.tsx", import.meta.url), "utf8");
const oidc = readFileSync(new URL("../src/lib/oidc.ts", import.meta.url), "utf8");
const operationalMessages = readFileSync(new URL("../src/lib/operationalMessages.ts", import.meta.url), "utf8");
const zh = JSON.parse(readFileSync(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"));
const en = JSON.parse(readFileSync(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8"));

test("CHG-256 global admission reacts only to its stable denial code", () => {
  assert.match(authProvider, /code === "application_access_denied"/);
  assert.match(authProvider, /unavailableAccountCodes\.has\(code\).*redirectAccountUnavailable/s);
  assert.match(authProvider, /response\.status === 401[\s\S]*refresh\(\)/);
  assert.match(authProvider, /applicationAccess === "denied" && tokens/);
  assert.match(authProvider, /<ApplicationAccessDenied/);
  assert.doesNotMatch(deniedComponent, /AppShell|Notification|ApprovalWorkspace|ApiDocumentation/);
});

test("CHG-256 denial preserves tokens and uses a synchronous circuit breaker", () => {
  const transition = authProvider.slice(
    authProvider.indexOf("const enterApplicationAccessDenied"),
    authProvider.indexOf("const apiFetch"),
  );
  assert.match(transition, /applicationAccessRef\.current = "denied"/);
  assert.match(transition, /isFirstTransition/);
  assert.match(transition, /setCurrentUser\(null\)/);
  assert.doesNotMatch(transition, /setTokens\(null\)|refresh\(|login-recovery|location\.replace/);
  assert.match(authProvider, /recheckPromise\.current/);
});

test("CHG-256 return path remains allowlisted and memory-only", () => {
  assert.match(authProvider, /const deniedReturnPath = useRef\("\/"\)/);
  assert.match(authProvider, /safeReturnPath\(deniedReturnPath\.current\)/);
  assert.doesNotMatch(authProvider, /localStorage|sessionStorage|indexedDB|document\.cookie/);
  assert.match(oidc, /!knownRoute/);
  assert.doesNotMatch(oidc, /path === "\/access-denied"/);
});

test("CHG-256 route and hydration watchdog recognize authenticated denial", () => {
  assert.match(authProvider, /pathname === "\/access-denied"/);
  assert.match(layout, /path==='\/access-denied'/);
  assert.match(deniedRoute, /auth-loading/);
});

test("CHG-256 denial messages are localized and locale catalogs remain aligned", () => {
  const keys = [
    "applicationAccessDeniedEyebrow",
    "applicationAccessDeniedTitle",
    "applicationAccessDeniedDescription",
    "applicationAccessDeniedAccount",
    "applicationAccessDeniedGuidance",
    "applicationAccessDeniedRecheck",
    "applicationAccessDeniedRechecking",
    "applicationAccessDeniedStillDenied",
    "applicationAccessDeniedRecheckFailed",
  ];
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort());
  for (const key of keys) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
    assert.notEqual(zh[key], en[key]);
  }
  assert.match(operationalMessages, /application_access_denied: "applicationAccessDeniedDescription"/);
  assert.match(deniedComponent, /role="alert"/);
  assert.match(deniedComponent, /aria-live="polite"/);
});
