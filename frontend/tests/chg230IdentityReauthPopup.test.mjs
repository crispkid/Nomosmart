import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("CHG-230 security gates remain while CHG-238 uses same-tab reauthentication", async () => {
  const [workspace, systemPage, legacyResultRoute, authProvider, layout, backendRoute, deploymentBootstrap, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/system/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/auth/identity-reauth/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../backend/app/api/routes/identity_settings.py", import.meta.url), "utf8"),
    readFile(new URL("../../backend/app/deployment/bootstrap.py", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(workspace, /action=\{canEditSystemManagement \? \(identityUnlocked/);
  assert.match(workspace, /replaceSystemRoute\("identity", "pending"\)/);
  assert.match(workspace, /window\.location\.assign\(flow\.authorization_url\)/);
  assert.match(workspace, /completeIdentityReauth\(apiFetch\)/);
  assert.doesNotMatch(workspace, /window\.open|postMessage|window\.close/);

  assert.match(systemPage, /initialTab=\{initialTab\}/);
  assert.match(systemPage, /initialReauthResult=\{initialReauthResult\}/);
  assert.match(legacyResultRoute, /redirect\(`\/system\?tab=identity&reauth=\$\{canonicalResult\}`\)/);
  assert.doesNotMatch(legacyResultRoute, /postMessage|window\.close|password|access_token|refresh_token|id_token/i);
  assert.match(authProvider, /const routeBypassesAuth = !protectedPath/);
  assert.doesNotMatch(authProvider, /pathname === "\/auth\/identity-reauth"/);
  assert.match(layout, /var protectedPath=/);
  assert.doesNotMatch(layout, /path==='\/auth\/identity-reauth'/);

  assert.match(backendRoute, /PermissionAction\.EDIT/);
  assert.match(backendRoute, /return_path=f"\{SYSTEM_REAUTH_RESULT_PATH\}success"/);
  assert.match(backendRoute, /"cancelled" if error == "access_denied" else "error"/);
  assert.match(backendRoute, /response\.set_cookie\([\s\S]*httponly=True/);
  assert.match(deploymentBootstrap, /"directAccessGrantsEnabled": False/);
  assert.match(deploymentBootstrap, /"pkce\.code\.challenge\.method": "S256"/);

  for (const messages of [zh, en]) {
    assert.ok(messages.identityReauthToEdit);
    assert.ok(messages.identityReauthInterrupted);
    assert.ok(messages.identityReauthInvalidResult);
    assert.ok(messages.identityReauthCompleting);
  }
});
