import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  createIdentityUnlockGrant,
  emptyIdentitySettings,
  defaultSystemParameters,
  hasParameterErrors,
  identityUnlockDurationMs,
  isIdentityUnlockValid,
  validateIdentitySettings,
  validateSystemParameters
} from "../src/lib/systemManagement.ts";

const validIdentitySettings = {
  ...emptyIdentitySettings,
  issuer: "http://127.0.0.1:8080/realms/nomosmart",
  realm: "nomosmart",
  clientId: "nomosmart-frontend",
  audience: "nomosmart-backend",
  discoveryUrl: "http://127.0.0.1:8080/realms/nomosmart/.well-known/openid-configuration",
  keycloakEnabled: true,
  syncEnabled: true,
  schedule: "0 2 * * *",
  timezone: "Asia/Taipei"
};

test("system parameter defaults are valid", () => {
  assert.deepEqual(validateSystemParameters(defaultSystemParameters), {});
  assert.equal(hasParameterErrors({}), false);
});

test("system parameters reject unsafe ranges and invalid timezone", () => {
  const errors = validateSystemParameters({
    uploadLimitMb: 0,
    timezone: "Taipei",
    stagingTtlDays: 91,
    sessionDraftTtlMinutes: 4
  });
  assert.equal(hasParameterErrors(errors), true);
  assert.match(errors.uploadLimitMb, /1–1024/);
  assert.match(errors.timezone, /IANA/);
  assert.match(errors.stagingTtlDays, /1–90/);
  assert.match(errors.sessionDraftTtlMinutes, /0 或 5–120/);
});

test("system parameters accept bounded custom values", () => {
  assert.deepEqual(validateSystemParameters({
    uploadLimitMb: 250,
    timezone: "America/New_York",
    stagingTtlDays: 30,
    sessionDraftTtlMinutes: 0
  }), {});
  assert.deepEqual(validateSystemParameters({
    uploadLimitMb: 250,
    timezone: "America/New_York",
    stagingTtlDays: 30,
    sessionDraftTtlMinutes: 120
  }), {});
});

test("identity state starts empty and accepts backend-provided shared sync settings without credentials", () => {
  assert.equal(emptyIdentitySettings.issuer, "");
  assert.deepEqual(validateIdentitySettings(validIdentitySettings), {});
  assert.equal(validIdentitySettings.syncScope, "people_and_groups");
  assert.equal("bindPassword" in validIdentitySettings, false);
  assert.equal("bindDn" in validIdentitySettings, false);
  assert.equal("ldapHost" in validIdentitySettings, false);
});

test("break-glass card renders backend status evidence without lifecycle controls", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const api = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  const zh = await readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8");
  const en = await readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8");

  assert.match(api, /BreakGlassStatusResponse/);
  assert.match(api, /getBreakGlassStatus/);
  assert.match(source, /getBreakGlassStatus\(apiFetch\)\.catch\(\(\) => null\)/);
  assert.match(source, /breakGlassStatus\?\.username/);
  assert.match(source, /localizedBreakGlassStatus/);
  assert.doesNotMatch(source, /localizedMfaEvidence/);
  assert.doesNotMatch(api, /mfa_evidence/);
  assert.match(source, /evidenceStateText/);
  assert.match(source, /identityBreakGlassConfiguredDisabled/);
  assert.match(source, /identityBreakGlassSystemAdmin/);
  assert.match(source, /identityCredentialUpdate/);
  assert.match(source, /identityLifecycleControl/);
  assert.match(source, /identityRunbookEvidence/);
  assert.match(source, /identityAlertingEvidence/);
  assert.match(api, /credential_update_required/);
  assert.match(api, /runbook_evidence/);
  assert.match(api, /alerting_evidence/);
  assert.match(api, /lifecycle_control/);
  assert.doesNotMatch(source, /enableBreakGlass/i);
  assert.doesNotMatch(source, /rotateBreakGlass/i);
  assert.doesNotMatch(source, /breakGlassPassword/i);
  assert.match(zh, /identityBreakGlassConfiguredDisabled/);
  assert.match(en, /identityBreakGlassConfiguredDisabled/);
  assert.match(zh, /identityRunbookEvidence/);
  assert.match(en, /identityRunbookEvidence/);
});

test("identity candidates reject unsafe endpoints and malformed schedules", () => {
  const errors = validateIdentitySettings({
    ...validIdentitySettings,
    issuer: "http://insecure.local/realm",
    discoveryUrl: "not-a-url",
    schedule: "daily",
    timezone: "Taipei"
  });
  assert.match(errors.issuer, /HTTPS/);
  assert.match(errors.discoveryUrl, /HTTPS/);
  assert.match(errors.schedule, /Cron/);
  assert.match(errors.timezone, /IANA/);
});

test("identity unlock is bound to user, session, scope, permission and ten-minute expiry", () => {
  const issuedAt = Date.UTC(2026, 5, 22, 3, 0, 0);
  const grant = createIdentityUnlockGrant("admin-1", "session-a", issuedAt);
  assert.equal(grant.expiresAt - grant.issuedAt, identityUnlockDurationMs);
  assert.equal(isIdentityUnlockValid(grant, { userId: "admin-1", sessionId: "session-a", now: issuedAt + 599_999, canEdit: true }), true);
  assert.equal(isIdentityUnlockValid(grant, { userId: "admin-1", sessionId: "session-a", now: issuedAt + 600_000, canEdit: true }), false);
  assert.equal(isIdentityUnlockValid(grant, { userId: "admin-2", sessionId: "session-a", now: issuedAt, canEdit: true }), false);
  assert.equal(isIdentityUnlockValid(grant, { userId: "admin-1", sessionId: "session-b", now: issuedAt, canEdit: true }), false);
  assert.equal(isIdentityUnlockValid(grant, { userId: "admin-1", sessionId: "session-a", now: issuedAt, canEdit: false }), false);
});

test("system prompt global boxes are direct edit or create entry points", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /systemPromptAddGlobalChat/);
  assert.doesNotMatch(source, /systemPromptAddGlobalJudge/);
  assert.match(source, /globalChatPrompt \? <button/);
  assert.match(source, /selectPrompt\(globalChatPrompt\)/);
  assert.match(source, /createGlobalPrompt\("Chat"\)/);
  assert.match(source, /globalJudgePrompt \? <button/);
  assert.match(source, /selectPrompt\(globalJudgePrompt\)/);
  assert.match(source, /createGlobalPrompt\("Judge"\)/);
  assert.match(source, /systemPromptGlobalMissing/);
});

test("system prompt editor opens as a dismissible modal", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");
  assert.match(source, /promptEditorOpen/);
  assert.match(source, /promptEditorPrompt/);
  assert.match(source, /activePromptEditor/);
  assert.match(source, /promptDraftSourceVersion/);
  assert.match(source, /setPromptEditorOpen\(true\)/);
  assert.match(source, /setPromptEditorPrompt\(prompt\)/);
  assert.match(source, /system-prompt-title-row/);
  assert.match(source, /activePromptEditor\.prompt_scope/);
  assert.doesNotMatch(source, /systemPromptModalEyebrow/);
  assert.match(styles, /\.system-prompt-modal > header \{[\s\S]*align-items: center/);
  assert.match(styles, /\.system-prompt-title-row \{[\s\S]*justify-content: space-between/);
  assert.match(styles, /\.system-prompt-badges \{[\s\S]*justify-content: flex-end/);
  assert.doesNotMatch(source, /systemPromptEditingSummary/);
  assert.doesNotMatch(source, /system-prompt-editor-header/);
  assert.match(source, /loadPromptVersionDraft/);
  assert.match(source, /systemPromptVersionAppendOnlyHelp/);
  assert.match(source, /systemPromptLoadVersionDraft/);
  assert.match(source, /system-prompt-layer-stack/);
  assert.doesNotMatch(source, /promptLayerHelp/);
  assert.doesNotMatch(source, /systemPromptGlobalLayerHelp/);
  assert.doesNotMatch(source, /systemPromptModelLayerHelp/);
  assert.match(source, /role="dialog"/);
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /systemPromptCloseEditor/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /event\.target === event\.currentTarget/);
  assert.doesNotMatch(source, /systemPromptChangeReason/);
  assert.doesNotMatch(source, /promptReason/);
  assert.doesNotMatch(source, /editor-area/);
});

test("model-specific system prompt rows communicate clickability", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");
  assert.match(source, /system-table-wrap system-prompt-model-table/);
  assert.match(source, /onClick=\{\(\) => selectPrompt\(prompt\)\}/);
  assert.match(styles, /\.system-prompt-model-table tbody tr \{ cursor: pointer; \}/);
});

test("system prompt editor blocks blank content before save or activation", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  assert.match(source, /promptDraftBlank = promptDraft\.trim\(\)\.length === 0/);
  assert.match(source, /currentPromptBlank = prompt\.content\.trim\(\)\.length === 0/);
  assert.match(source, /systemPromptBlankContentError/);
  assert.match(source, /promptDraftBlank \|\| promptDraft\.length > 8000/);
  assert.match(source, /prompt\.is_active \|\| currentPromptBlank/);
});

test("system management exposes API key lifecycle management", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const api = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  const zh = await readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8");
  const en = await readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8");

  assert.match(source, /id: "apiKeys"/);
  assert.match(source, /listIntegrationClients\(apiFetch\)/);
  assert.match(source, /createIntegrationClient\(apiFetch/);
  assert.match(source, /rotateIntegrationClientKey\(apiFetch/);
  assert.match(source, /revokeIntegrationClient\(apiFetch/);
  assert.match(source, /updateIntegrationClient\(apiFetch/);
  assert.match(source, /apiKeyOneTime/);
  assert.match(source, /systemApiKeyOneTimeHelp/);
  assert.match(source, /system-api-key-onetime-title/);
  assert.match(source, /replaceIntegrationClientProjectScopes/);
  assert.match(api, /export type IntegrationClientResponse/);
  assert.match(api, /api_key: string/);
  assert.match(api, /\/integration-clients/);
  assert.match(zh, /"systemApiKeys": "API Key 管理"/);
  assert.match(en, /"systemApiKeys": "API Key Management"/);
});

test("API key management uses modal create and selected-client management flows", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const styles = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");
  const zh = await readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8");
  const en = await readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8");

  assert.match(source, /openApiKeyCreateModal/);
  assert.match(source, /setModal\(\{ type: "api-key-create" \}\)/);
  assert.match(source, /modal.type === "api-key-create"/);
  assert.match(source, /modal.type === "api-key-manage"/);
  assert.match(source, /openApiKeyManageModal\(client\)/);
  assert.match(source, /systemApiKeyManageTitle/);
  assert.match(source, /saveApiKeyManagement\(modal.client/);
  assert.match(source, /systemApiKeyRevokeConfirm/);
  assert.match(source, /systemApiKeyAuthorizedProjects/);
  assert.match(source, /system-api-key-modal-form/);
  assert.doesNotMatch(source, /className="system-api-key-create"/);
  assert.doesNotMatch(source, /system-api-key-layout/);
  assert.doesNotMatch(source, /system-api-project-picker compact/);
  assert.match(styles, /\.system-api-key-scope-summary/);
  assert.match(styles, /\.system-api-key-modal-actions/);
  assert.match(styles, /\.system-api-key-onetime-modal/);
  assert.match(zh, /"systemApiKeyManageTitle": "管理 Integration Client"/);
  assert.match(en, /"systemApiKeyManageTitle": "Manage Integration Client"/);
  assert.match(zh, /systemApiKeyRevokeConfirm/);
  assert.match(en, /systemApiKeyRevokeConfirm/);
});

test("AI model pricing supports ISO currency and explicit zero prices", async () => {
  const source = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  const reports = await readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8");
  const reportExport = await readFile(new URL("../src/lib/reportExport.ts", import.meta.url), "utf8");
  const api = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  const zh = await readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8");
  const en = await readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8");

  assert.match(source, /input_cost_per_million_tokens/);
  assert.match(source, /embedding_cost_per_million_tokens/);
  assert.match(source, /ocr_cost_per_page/);
  assert.match(source, /min="0"/);
  assert.match(source, /name="cost_currency"/);
  assert.match(source, /systemModelPricingCurrencyRequired/);
  assert.doesNotMatch(reports, /integrationClientId/);
  assert.match(reports, /usagePurpose/);
  assert.doesNotMatch(reports, /provider_reported_cost/);
  assert.doesNotMatch(reports, /cost_source/);
  assert.match(reportExport, /provider_reported_cost/);
  assert.match(reportExport, /cost_source/);
  assert.match(reportExport, /embedding_tokens/);
  assert.match(reportExport, /ocr_pages/);
  assert.match(api, /type ModelUsageReportFilters/);
  assert.match(zh, /"systemModelPricingTitle": "成本估算設定"/);
  assert.match(en, /"systemModelPricingTitle": "Cost estimation"/);
});
