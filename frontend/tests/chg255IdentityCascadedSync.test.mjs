import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("CHG-255 shows localized cascading phases and provider results", async () => {
  const [workspace, api, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(api, /requested_scope/);
  assert.match(api, /provider_results/);
  assert.match(api, /user_sync_status/);
  assert.match(api, /group_sync_status/);
  assert.match(workspace, /identitySyncProgressText/);
  assert.match(workspace, /identity-provider-results/);
  assert.match(workspace, /identitySyncErrorKey/);
  assert.match(workspace, /await refreshIdentityData\(\)/);
  assert.match(workspace, /provider\.provider_name/);
  assert.doesNotMatch(workspace, /provider\.error_message|provider\.raw/);

  const requiredKeys = [
    "identitySyncPhaseProviderDiscovery",
    "identitySyncPhaseProviderUsers",
    "identitySyncPhaseProviderGroups",
    "identitySyncPhaseSnapshot",
    "identitySyncPhaseReconciliation",
    "identitySyncProgressProvider",
    "identitySyncProviderResults",
    "identitySyncGroupMapperMissing",
    "identitySyncProviderTimeout"
  ];
  for (const key of requiredKeys) {
    assert.ok(zh[key], `missing zh key ${key}`);
    assert.ok(en[key], `missing en key ${key}`);
  }
});
