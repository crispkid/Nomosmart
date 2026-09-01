import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("CHG-234 renders backend truth, real providers, protected filters, and polled sync state", async () => {
  const [workspace, api, settings, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/systemManagement.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(settings, /emptyIdentitySettings/);
  assert.doesNotMatch(settings, /sso\.nomosmart\.local|Corporate LDAP|Windows Active Directory/);
  assert.doesNotMatch(workspace, /22 groups|682 users|2,132 users|identityCheckedThreeMinutesAgo/);
  assert.match(api, /listDirectoryProviders/);
  assert.match(api, /updateDirectoryProviderFilter/);
  assert.match(api, /getIdentitySyncRun/);
  assert.match(workspace, /identitySettingsFromConfiguration\(identityPayload\.configuration\)/);
  assert.match(workspace, /directoryProviders\.map\(\(provider\)/);
  assert.match(workspace, /directoryFilterDrafts\[provider\.id\]/);
  assert.match(workspace, /!identityUnlocked \|\| !canEditSystemManagement/);
  assert.match(workspace, /while \(run\.status === "queued" \|\| run\.status === "running"\)/);
  assert.match(workspace, /identity_sync_worker_unavailable/);
  assert.match(workspace, /identityConfigurationSource/);

  for (const messages of [zh, en]) {
    assert.ok(messages.identityDirectoryFilter);
    assert.ok(messages.identityDirectoryProviderUnavailable);
    assert.ok(messages.identitySyncWorkerUnavailable);
    assert.ok(messages.identitySourceDeployment);
  }
});
