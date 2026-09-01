import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { authorizationUrl, oidcConfig, pkceChallenge, safeReturnPath } from "../src/lib/oidc.ts";

test("OIDC uses a public client, authorization code and PKCE S256", async () => {
  const challenge = await pkceChallenge("verifier-for-test");
  const url = new URL(authorizationUrl(oidcConfig(), { state: "state", nonce: "nonce", challenge }));
  assert.equal(url.pathname, "/realms/nomosmart/protocol/openid-connect/auth");
  assert.equal(url.searchParams.get("client_id"), "nomosmart-frontend");
  assert.equal(url.searchParams.get("response_type"), "code");
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.ok(challenge.length > 30);
});

test("server-side OIDC transport is separate from the browser-visible issuer", async () => {
  const [oidc, start, exchange, refresh] = await Promise.all([
    readFile(new URL("../src/lib/oidc.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/start/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/exchange/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/refresh/route.ts", import.meta.url), "utf8")
  ]);
  assert.match(oidc, /FRONTEND_OIDC_INTERNAL_ISSUER_URL/);
  assert.match(oidc, /internalIssuer: runtime\.oidcInternalIssuerUrl/);
  assert.match(oidc, /authorizationUrl[\s\S]*config\.issuer/);
  for (const route of [start, exchange, refresh]) assert.match(route, /config\.internalIssuer/);
  for (const route of [start, exchange, refresh]) assert.doesNotMatch(route, /fetch\(`\$\{config\.issuer\}/);
});

test("OIDC return paths reject open redirects and callback loops", () => {
  assert.equal(safeReturnPath("/projects?state=active"), "/projects?state=active");
  assert.equal(safeReturnPath("https://evil.test"), "/");
  assert.equal(safeReturnPath("//evil.test"), "/");
  assert.equal(safeReturnPath("/login"), "/");
  assert.equal(safeReturnPath("/auth/callback?again=1"), "/");
  assert.equal(safeReturnPath("/api/auth/start"), "/");
  assert.equal(safeReturnPath("/route-that-does-not-exist"), "/");
});

test("formal auth runtime keeps tokens out of persistent browser storage", async () => {
  const files = ["../src/components/AuthProvider.tsx", "../src/components/OidcCallback.tsx", "../src/app/api/auth/logout/route.ts", "../src/lib/oidc.ts"];
  const source = (await Promise.all(files.map((file) => readFile(new URL(file, import.meta.url), "utf8")))).join("\n");
  for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) assert.equal(source.includes(forbidden), false);
  assert.match(source, /response\.status === 401/);
  assert.doesNotMatch(source, /response\.status === 403[^\n]*refresh/);
});

test("session expiry uses database-backed form drafts without browser payload storage", async () => {
  const [provider, drafts, system, zh, en] = await Promise.all([
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/sessionDrafts.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.match(provider, /mode=session_expired&returnTo=/);
  assert.match(provider, /AbortSignal\.timeout\(1500\)/);
  assert.doesNotMatch(provider, /setSessionExpired/);
  assert.equal(zh.loginNoticeSessionExpired, "登入狀態已過期，請重新登入。");
  assert.equal(en.loginNoticeSessionExpired, "Your session has expired. Please sign in again.");
  assert.match(provider, /\/auth\/session-drafts/);
  assert.match(provider, /nomosmart:restore-session-draft/);
  assert.match(provider, /reauthDraftId/);
  assert.match(drafts, /data-session-draft-key/);
  assert.match(drafts, /isSensitiveField/);
  for (const forbidden of ["localStorage", "sessionStorage", "indexedDB"]) assert.equal(provider.includes(forbidden), false);
  assert.match(system, /data-session-draft-key="system\.parameters"/);
  assert.match(system, /sessionDraftTtlMinutes/);
});

test("secure logout calls backend, clears transient cookies and ends Keycloak session", async () => {
  const [provider, shell, logoutRoute, authState, zh, en] = await Promise.all([
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/logout/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/authState.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.match(provider, /apiBaseUrl\(\).*\/auth\/logout/);
  assert.match(provider, /Authorization: `Bearer \$\{current\.accessToken\}`/);
  assert.match(provider, /\/api\/auth\/logout/);
  assert.match(provider, /protocol\/openid-connect\/logout/);
  assert.match(provider, /setTokens\(null\)/);
  assert.match(shell, /role="menu"/);
  assert.match(shell, /role="menuitem"/);
  assert.match(shell, /t\("logout", locale\)/);
  assert.match(logoutRoute, /clearAuthorizationState\(response\)/);
  assert.match(logoutRoute, /"logged_out"/);
  for (const cookie of ["nomosmart_pkce", "nomosmart_state", "nomosmart_nonce", "nomosmart_return", "nomosmart_auth_flow", "nomosmart_login_notice"]) assert.match(authState, new RegExp(cookie));
  assert.equal(zh.logout, "登出");
  assert.equal(en.logout, "Logout");
});

test("login page redirects to Keycloak and contains no credential fields", async () => {
  const [source, sessionRedirect, zh, en] = await Promise.all([
    readFile(new URL("../src/app/login/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/LoginSessionRedirect.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.match(source, /href="\/api\/auth\/start"/);
  assert.doesNotMatch(source, /href="\/api\/auth\/start\?[^\"]*prompt=none/);
  assert.match(source, /parseLoginNotice/);
  assert.doesNotMatch(source, /searchParams/);
  assert.match(source, /loginNoticeSessionExpired/);
  assert.match(sessionRedirect, /\/api\/auth\/start\?prompt=none/);
  assert.match(sessionRedirect, /\/api\/auth\/continue/);
  assert.equal(zh.oidcCallbackError, "企業登入驗證失敗，請重新登入。");
  assert.equal(en.oidcCallbackError, "Enterprise sign-in verification failed. Please sign in again.");
  assert.equal(source.includes('type="password"'), false);
  assert.equal(source.includes("OTP"), false);
});

test("OIDC callback errors recover without client hydration and clear transient state", async () => {
  const [callbackPage, callbackClient, callbackErrorRoute, loginRecoveryRoute, authState, authStart] = await Promise.all([
    readFile(new URL("../src/app/auth/callback/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/OidcCallback.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/callback-error/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/login-recovery/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/authState.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/auth/start/route.ts", import.meta.url), "utf8")
  ]);
  assert.match(callbackPage, /await searchParams/);
  assert.match(callbackPage, /trustedState/);
  assert.match(callbackPage, /error === "login_required" && flow === "silent"/);
  assert.match(callbackPage, /error === "access_denied".*flow === "interactive".*flow === "session_expired"/s);
  assert.match(callbackPage, /AUTH_COOKIES\.state/);
  assert.match(callbackPage, /redirect\("\/api\/auth\/callback-error"\)/);
  assert.match(callbackPage, /<OidcCallback code=\{code\} state=\{state\}/);
  assert.doesNotMatch(callbackPage, /Suspense/);
  assert.doesNotMatch(callbackClient, /useSearchParams/);
  assert.match(callbackClient, /window\.setTimeout/);
  assert.match(callbackClient, /8000/);
  assert.match(callbackClient, /"oidc_error"/);
  assert.match(callbackClient, /mode=auth_service_unavailable/);
  assert.match(authStart, /get\("prompt"\) === "none" \? "none" : undefined/);
  assert.match(authStart, /AUTH_COOKIES\.flow/);
  assert.match(authStart, /priorNotice === "session_expired" \? "session_expired" : "interactive"/);
  assert.match(callbackErrorRoute, /createLoginRecoveryResponse\(request, "oidc_error"\)/);
  assert.match(loginRecoveryRoute, /parseLoginRecoveryMode/);
  assert.match(authState, /url\.pathname = "\/login"/);
  assert.match(authState, /url\.search = ""/);
  assert.match(authState, /httpOnly: true/);
  assert.match(authState, /sameSite: "lax"/);
  assert.doesNotMatch(authState, /searchParams\.set\("error"/);
});

test("auth responses distinguish expiry, account state and permission failures", async () => {
  const provider = await readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8");
  assert.match(provider, /response\.status === 401/);
  assert.match(provider, /await refresh\(\)/);
  assert.match(provider, /user_disabled/);
  assert.match(provider, /user_not_synchronized/);
  assert.match(provider, /response\.status === 403/);
  assert.match(provider, /unavailableAccountCodes\.has\(code\).*redirectAccountUnavailable/s);
  assert.match(provider, /code === "application_access_denied".*enterApplicationAccessDenied/s);
  assert.doesNotMatch(provider, /permission_denied.*login-recovery/s);
  assert.doesNotMatch(provider, /project_scope_denied.*login-recovery/s);
});

test("protected auth loading has hydration and no-script recovery within five seconds", async () => {
  const [provider, layout] = await Promise.all([
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/layout.tsx", import.meta.url), "utf8")
  ]);
  assert.match(provider, /__NOMOSMART_AUTH_HYDRATED__/);
  assert.match(provider, /<noscript><meta httpEquiv="refresh" content="5;url=\/login"/);
  assert.doesNotMatch(provider, /<script dangerouslySetInnerHTML/);
  assert.match(layout, /nomosmart-auth-hydration-watchdog/);
  assert.match(layout, /5000/);
  assert.match(layout, /var protectedPath=path==='\/'/);
  assert.doesNotMatch(layout, /path==='\/auth\/callback'/);
  assert.doesNotMatch(layout, /path==='\/setup'/);
  assert.match(layout, /window\.location\.replace\('\/login'\)/);
});

test("development output is isolated and a live dev server blocks production build", async () => {
  const [config, eslintConfig, gitignore, packageJson, buildGuard] = await Promise.all([
    readFile(new URL("../next.config.ts", import.meta.url), "utf8"),
    readFile(new URL("../eslint.config.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../.gitignore", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../scripts/next-build.mjs", import.meta.url), "utf8")
  ]);
  assert.match(config, /NODE_ENV === "development" \? "\.next-dev" : "\.next"/);
  assert.match(config, /FRONTEND_ALLOWED_DEV_ORIGINS/);
  assert.match(config, /new URL\(appOrigin\)\.hostname/);
  assert.match(config, /allowedDevOrigins: allowedDevOrigins\(\)/);
  assert.match(eslintConfig, /"\.next-dev\/\*\*"/);
  assert.match(gitignore, /frontend\/\.next-dev\//);
  assert.equal(packageJson.scripts.build, "node scripts/next-build.mjs");
  assert.match(buildGuard, /\.next-dev\/dev\/lock/);
  assert.match(buildGuard, /process\.kill\(lock\.pid, 0\)/);
  assert.match(buildGuard, /Production build refused/);
  assert.match(buildGuard, /spawn\(process\.execPath/);
});

test("Keycloak theme owns the password-only form", async () => {
  const [login, theme] = await Promise.all([
    readFile(new URL("../../deploy/keycloak/themes/nomosmart/login/login.ftl", import.meta.url), "utf8"),
    readFile(new URL("../../deploy/keycloak/themes/nomosmart/login/theme.properties", import.meta.url), "utf8")
  ]);
  assert.match(login, /url\.loginAction/); assert.match(login, /autocomplete="current-password"/);
  assert.match(theme, /parent=keycloak\.v2/);
});
