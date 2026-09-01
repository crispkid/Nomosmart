import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  parseIdentityReauthResult,
  parseSystemTab,
  systemRouteUrl,
  systemTabIds
} from "../src/lib/systemRouteState.ts";

test("CHG-238 accepts only canonical System Management tabs", () => {
  for (const tab of systemTabIds) assert.equal(parseSystemTab(tab), tab);
  assert.equal(parseSystemTab(undefined), "users");
  assert.equal(parseSystemTab("unknown"), "users");
  assert.equal(parseSystemTab(["identity", "users"]), "users");
});

test("CHG-238 accepts only enumerated reauthentication results", () => {
  for (const result of ["pending", "success", "cancelled", "error"]) {
    assert.equal(parseIdentityReauthResult(result), result);
  }
  assert.equal(parseIdentityReauthResult("waiting"), null);
  assert.equal(parseIdentityReauthResult("success&token=secret"), null);
  assert.equal(parseIdentityReauthResult(["success", "error"]), null);
});

test("CHG-238 canonical URL updates preserve unrelated state and remove handled results", () => {
  assert.equal(
    systemRouteUrl("http://127.0.0.1:3000/system?tab=users&filter=active#roles", "identity", "pending"),
    "/system?tab=identity&filter=active&reauth=pending#roles"
  );
  assert.equal(
    systemRouteUrl("/system?tab=identity&reauth=success&reauthDraftId=draft", "identity", null),
    "/system?tab=identity&reauthDraftId=draft"
  );
});

test("CHG-238 renders the requested tab first and uses replace-only same-tab flow", async () => {
  const [page, workspace, authProvider, backendRoute] = await Promise.all([
    readFile(new URL("../src/app/system/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../backend/app/api/routes/identity_settings.py", import.meta.url), "utf8")
  ]);

  assert.match(page, /const initialTab = parseSystemTab\(query\.tab\)/);
  assert.match(workspace, /useState<TabId>\(initialTab\)/);
  assert.match(workspace, /window\.history\.replaceState\(window\.history\.state/);
  assert.doesNotMatch(workspace, /localStorage|sessionStorage|history\.pushState/);
  assert.match(workspace, /window\.location\.assign\(flow\.authorization_url\)/);
  assert.match(workspace, /window\.addEventListener\("pageshow", handlePageShow\)/);
  assert.match(workspace, /identityReauthResultProcessedRef/);
  assert.doesNotMatch(workspace, /window\.open|postMessage|window\.close/);
  assert.match(authProvider, /encodeURIComponent\(`\$\{pathname\}\$\{window\.location\.search\}`\)/);
  assert.match(backendRoute, /SYSTEM_REAUTH_RESULT_PATH = "\/system\?tab=identity&reauth="/);
  assert.doesNotMatch(backendRoute, /POPUP_RESULT_PATH|_popup_result_url/);
});
