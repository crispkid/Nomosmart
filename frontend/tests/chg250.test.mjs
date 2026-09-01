import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("CHG-250 blocks project creation until all compatible active AI models are ready", async () => {
  const [projects, api, css, zh, en] = await Promise.all([
    readFile(new URL("../src/app/projects/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse),
  ]);

  assert.match(api, /llm_model_id: string;\s+embedding_model_id: string;\s+ocr_model_id: string;/);
  assert.match(projects, /modelLoadState.*"idle" \| "loading" \| "ready" \| "error"/);
  assert.match(projects, /model\.is_active && !model\.deleted_at/);
  assert.match(projects, /const missingModelTypes = \[/);
  assert.match(projects, /const hasCompatibleModelPair = activeChatModels\.some/);
  assert.match(projects, /const modelReadinessBlocked = modelLoadState !== "ready" \|\| missingModelTypes\.length > 0 \|\| !hasCompatibleModelPair/);
  assert.match(projects, /role="alert"/);
  assert.match(projects, /aria-describedby=\{modelReadinessBlocked \? "project-model-readiness" : undefined\}/);
  assert.match(projects, /href="\/system\?tab=models"/);
  assert.match(projects, /can\("Menu", "SystemManagement", "view"\)/);
  assert.match(projects, /projectsContactAdministrator/);
  assert.match(projects, /llm_model_id: llmModelId,\s+embedding_model_id: effectiveEmbeddingModelId,\s+ocr_model_id: ocrModelId/);
  assert.doesNotMatch(projects, /(?:llm|embedding|ocr)_model_id: [^,\n]+ \|\| null/);
  assert.match(css, /\.project-model-readiness\s*\{/);
  assert.match(css, /border-left: 3px solid var\(--soft-coral\)/);
  for (const key of [
    "projectsModelReadinessTitle",
    "projectsModelReadinessMissing",
    "projectsModelReadinessLoading",
    "projectsModelReadinessLoadFailed",
    "projectsGoToAiModels",
    "projectsContactAdministrator",
    "projectsCreateDisabledModels",
  ]) {
    assert.equal(typeof zh[key], "string", `missing zh key ${key}`);
    assert.equal(typeof en[key], "string", `missing en key ${key}`);
  }
});

test("CHG-250 localizes runtime operational messages and preserves request IDs", async () => {
  const [api, messages, i18n, shell, guard, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/operationalMessages.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/i18n.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../eslint-rules/no-untranslated-visible-text.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse),
  ]);

  assert.match(api, /requestId\?: string/);
  assert.match(api, /request_id\?: string/);
  assert.match(api, /error\.requestId = body\.request_id/);
  assert.match(messages, /project_model_configuration_required: "projectsModelConfigurationRequired"/);
  assert.match(messages, /project_model_pair_required: "projectsModelPairRequired"/);
  assert.match(messages, /withRequestId/);
  assert.doesNotMatch(messages, /return error\.message/);
  assert.match(i18n, /export function localizeKnownMessageOrNull/);
  assert.match(i18n, /templateParameters/);
  assert.match(shell, /notificationCopyKeys/);
  assert.match(shell, /notification\.notification_type/);
  assert.doesNotMatch(shell, /<strong>\{notification\.title\}<\/strong>/);
  assert.doesNotMatch(shell, /<p>\{notification\.message\}<\/p>/);
  assert.match(guard, /runtimeMessage/);
  assert.match(guard, /error_message/);
  assert.match(guard, /error_summary/);
  assert.match(guard, /block_reasons/);
  for (const key of [
    "apiGenericError",
    "apiErrorWithRequestId",
    "apiNetworkError",
    "notificationReviewManagerPendingTitle",
    "notificationDocumentPublishedMessage",
    "notificationGenericMessage",
  ]) {
    assert.equal(typeof zh[key], "string", `missing zh key ${key}`);
    assert.equal(typeof en[key], "string", `missing en key ${key}`);
  }
});
