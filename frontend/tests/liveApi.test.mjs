import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("typed API client defines permission helpers from backend grants", async () => {
  const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  assert.match(source, /export function can\(/);
  assert.match(source, /grant\.module_name === moduleName/);
  assert.match(source, /grant\.function_name === functionName/);
  assert.match(source, /grant\[key\]/);
  assert.match(source, /export function canAnyView/);
});

test("typed API client exposes database-backed session draft APIs", async () => {
  const source = await readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  for (const helper of ["createSessionDraft", "restoreSessionDraft", "discardSessionDraft"]) assert.match(source, new RegExp(`export async function ${helper}`));
  assert.match(source, /session_expired_form_draft_ttl_minutes/);
});

test("auth provider bootstraps session from /auth/me and keeps tokens memory-only", async () => {
  const [source, api, oidc, proxy] = await Promise.all([
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/oidc.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/api/backend/[...path]/route.ts", import.meta.url), "utf8")
  ]);
  assert.match(source, /getCurrentUser\(bootstrapFetch\)/);
  assert.match(source, /const bootstrapFetch/);
  assert.match(source, /response\.status !== 401/);
  assert.match(source, /response\.ok && !cancelled\) setTokens\(next\)/);
  assert.match(api, /export type ApiError = Error & \{ status: number; code: string/);
  assert.match(source, /error: ApiError/);
  assert.match(source, /setTokens\(null\)/);
  assert.match(source, /mode=session_expired/);
  assert.doesNotMatch(source, /setSessionExpired/);
  assert.match(source, /formatPersonName\(currentUser, locale\)/);
  assert.match(api, /given_name: string \| null/);
  assert.match(api, /family_name: string \| null/);
  assert.match(source, /protectedContentReady/);
  assert.match(source, /tokens && authReady && currentUser/);
  assert.match(source, /authLoadFailed/);
  assert.match(source, /useI18n/);
  assert.match(oidc, /authRuntimeConfig\(\)\.apiBaseUrl/);
  assert.match(proxy, /BACKEND_INTERNAL_API_BASE_URL/);
  assert.match(proxy, /request\.headers\.forEach/);
  assert.match(proxy, /backend_proxy_unreachable/);
  for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) assert.equal(source.includes(forbidden), false);
});

test("system initialization wizard and API client surface are retired", async () => {
  const [auth, layout, api, zh, en] = await Promise.all([
    readFile(new URL("../src/components/AuthProvider.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  await assert.rejects(readFile(new URL("../src/app/setup/page.tsx", import.meta.url), "utf8"), { code: "ENOENT" });
  for (const source of [auth, layout, api]) {
    assert.doesNotMatch(source, /\/setup/);
    assert.doesNotMatch(source, /system-initialization/);
    assert.doesNotMatch(source, /SystemInitialization/);
  }
  assert.equal(Object.keys(zh).some((key) => key.startsWith("init")), false);
  assert.equal(Object.keys(en).some((key) => key.startsWith("init")), false);
});

test("app shell exposes a header language switcher that updates html lang", async () => {
  const [source, i18n, i18nClient] = await Promise.all([
    readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/i18n.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/i18nClient.ts", import.meta.url), "utf8")
  ]);
  for (const required of [
    "language-switcher",
    "languageSwitcher",
    "supportedLocales",
    "language-switcher-trigger",
    "language-menu-panel",
    "role=\"menuitemradio\"",
    "aria-haspopup=\"menu\""
  ]) assert.match(source, new RegExp(required.replace(/[()]/g, "\\$&")));
  for (const required of ["繁體中文", "English", "zh-Hant"]) {
    assert.match(i18n, new RegExp(required.replace(/[()]/g, "\\$&")));
  }
  for (const required of ["nomosmart_locale", "document.documentElement.lang", "htmlLangForLocale", "useSyncExternalStore"]) {
    assert.match(i18nClient, new RegExp(required.replace(/[()]/g, "\\$&")));
  }
});

test("language switcher locale keys stay aligned", async () => {
  const [zh, en] = await Promise.all([
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.equal(zh.languageSwitcher, "語言切換");
  assert.equal(en.languageSwitcher, "Language switcher");
});

test("AppShell page headers render only the primary title", async () => {
  const pageFiles = [
    "../src/app/page.tsx",
    "../src/app/projects/page.tsx",
    "../src/app/project/[id]/import/page.tsx",
    "../src/app/project/[id]/knowledge/[knowledgeId]/page.tsx",
    "../src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx",
    "../src/app/project/[id]/knowledge/[knowledgeId]/submit-review/page.tsx",
    "../src/app/approve/page.tsx",
    "../src/app/approve/[approvalTaskId]/page.tsx",
    "../src/app/reports/page.tsx",
    "../src/app/system/page.tsx",
    "../src/app/api-docs/page.tsx"
  ];
  const [shell, css, ...pages] = await Promise.all([
    readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    ...pageFiles.map((file) => readFile(new URL(file, import.meta.url), "utf8"))
  ]);

  assert.match(shell, /AppShell\(\{ children, title \}/);
  assert.doesNotMatch(shell, /eyebrow/);
  assert.match(shell, /<header className="topbar">[\s\S]*<h1>\{title\}<\/h1>/);
  for (const page of pages) assert.doesNotMatch(page, /<AppShell\b[^>]*\beyebrow=/s);
  assert.match(pages.join("\n"), /<p className="eyebrow">/);
  assert.doesNotMatch(css, /\.eyebrow\s*\{[^}]*display\s*:\s*none/s);
  assert.match(css, /\.topbar h1\s*\{\s*margin: 0;/);
});

test("projects page uses live backend APIs and project import uses live-only document state", async () => {
  const [api, projects, importPage, memberAutocomplete, css, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/projects/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectMemberAutocomplete.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of ["listProjectsPage(apiFetch", "createProject(apiFetch", "listModels(apiFetch)"]) assert.match(projects, new RegExp(required.replace(/[()]/g, "\\$&")));
  assert.match(projects, /limit: PROJECT_PAGE_SIZE/);
  assert.match(projects, /signal: controller\.signal/);
  assert.match(api, /response\.headers\.get\("X-Total-Count"\)/);
  assert.match(projects, /can\("Menu", "KnowledgeProjects", "view"\)/);
  assert.match(projects, /can\("Menu", "KnowledgeProjects", "create"\)/);
  assert.match(projects, /model\.model_type\.toLowerCase\(\) === "chat"/);
  assert.match(projects, /const activeChatModels = useMemo/);
  assert.match(projects, /model\.is_active && !model\.deleted_at/);
  assert.match(projects, /modelStateLabel\(model\.is_active\)/);
  assert.match(projects, /model\.model_type\.toLowerCase\(\) === "ocr"/);
  assert.match(projects, /const defaultOcr = modelRows\.find/);
  assert.match(projects, /ocr_model_id: ocrModelId/);
  assert.match(projects, /const modelGroupKeys = \[/);
  assert.match(projects, /function modelPairKey\(model: AIModelResponse\)/);
  assert.match(projects, /function pairedEmbeddingModelIds\(model: AIModelResponse\)/);
  assert.match(projects, /model\.config\.paired_embedding_model_ids/);
  assert.match(projects, /model\.config\[key\]/);
  assert.match(projects, /provider:\$\{model\.provider\.trim\(\)\.toLowerCase\(\)\}/);
  assert.match(projects, /pairedEmbeddingModels/);
  assert.match(projects, /const explicitPairedEmbeddingIds = selectedLlmModel \? pairedEmbeddingModelIds\(selectedLlmModel\) : \[\]/);
  assert.match(projects, /explicitPairedEmbeddingIds\.length[\s\S]*activeEmbeddingModels\.filter\(\(model\) => explicitPairedEmbeddingIds\.includes\(model\.id\)\)/);
  assert.match(projects, /effectiveEmbeddingModelId/);
  assert.match(projects, /pairedDefaultEmbeddingModel/);
  assert.match(projects, /projectsModelPairRequired/);
  assert.match(projects, /disabled=\{creating \|\| modelReadinessBlocked \|\| !selectedLlmModel \|\| !hasActivePairedEmbeddingModel \|\| !ocrModelId \|\| !effectiveEmbeddingModelId\}/);
  assert.match(projects, /t\("projectsOcrModel"\)/);
  const basicSectionIndex = projects.indexOf('t("projectsBasicInfo")');
  const ocrSectionIndex = projects.indexOf('t("projectsOcrModel")');
  const llmSectionIndex = projects.indexOf('t("projectsLlmModel")');
  const embeddingSectionIndex = projects.indexOf('t("projectsEmbeddingModel")');
  assert.ok(basicSectionIndex < ocrSectionIndex, "Create Project should place OCR to the right of basic info");
  assert.ok(ocrSectionIndex < llmSectionIndex, "Create Project should place LLM after the top row");
  assert.ok(llmSectionIndex < embeddingSectionIndex, "Create Project should place Embedding after LLM");
  assert.equal(zh.projectsOcrModel, "OCR 模型");
  assert.equal(en.projectsOcrModel, "OCR model");
  assert.match(zh.projectsEmbeddingPairHelp, /模型組/);
  assert.match(en.projectsEmbeddingPairHelp, /model group/);
  assert.match(zh.projectsModelPairRequired, /LLM 與向量模型/);
  assert.match(en.projectsModelPairRequired, /LLM and Embedding model pair/);
  assert.match(projects, /className="create-project-scroll"/);
  assert.match(css, /\.create-project-modal[\s\S]*overflow: hidden/);
  assert.match(css, /\.create-project-scroll[\s\S]*overflow-y: auto/);
  assert.match(css, /\.create-project-modal > \.modal-actions[\s\S]*position: sticky/);
  assert.doesNotMatch(projects, /members:/);
  assert.doesNotMatch(projects, /listUsers\(apiFetch\)/);
  assert.doesNotMatch(projects, /projectsInitialOwners/);
  assert.doesNotMatch(projects, /create-owner-/);
  assert.doesNotMatch(projects, /ownerMembers/);
  assert.doesNotMatch(projects, /UserRoundCog/);
  assert.doesNotMatch(projects, /UserPlus/);
  assert.doesNotMatch(projects, /roleDefinitions/);
  assert.doesNotMatch(projects, /membersByRole/);
  assert.doesNotMatch(projects, /role-menu/);
  assert.doesNotMatch(projects, /projectsAddToRole/);
  assert.doesNotMatch(css, /\.create-owner-/);
  assert.equal(zh.projectsAddProject, "新增專案");
  assert.equal(en.projectsAddProject, "Add project");
  assert.match(importPage, /getProject\(apiFetch, params\.id\)/);
  assert.match(importPage, /documentLoadState/);
  assert.match(importPage, /listProjectDocuments\(apiFetch, params\.id\)/);
  assert.match(api, /versions\?: DocumentVersionSummary\[\]/);
  assert.match(importPage, /const versionRows = document\.versions\?\.length \? document\.versions : version \? \[version\] : \[\]/);
  assert.match(importPage, /const hasActiveVersion = versionRows\.some\(\(item\) => item\.status === "active"\)/);
  assert.match(importPage, /extractionSuccessful: hasActiveVersion/);
  assert.match(importPage, /versions: versionRows\.map/);
  assert.match(api, /export type ProjectMemberResponse/);
  assert.match(api, /listProjectMembers\(apiFetch: ApiFetch, projectId: string\)/);
  assert.match(api, /replaceProjectMember\(apiFetch: ApiFetch, projectId: string, userId: string/);
  assert.match(api, /removeProjectMember\(apiFetch: ApiFetch, projectId: string, userId: string, lockVersion: number\)/);
  assert.match(importPage, /setActiveModal\("chat"\)[\s\S]*projectImportPermissionManagement/);
  assert.doesNotMatch(importPage, /Owner Linda Chen/);
  assert.doesNotMatch(importPage, /Project role Owner/);
  assert.doesNotMatch(importPage, /<StatusBadge status="processing" \/>/);
  assert.match(importPage, /const \{ apiFetch, currentUser \} = useAuth\(\)/);
  assert.match(importPage, /const canManageProjectPermissions = project\?\.is_owner \?\? false/);
  assert.match(importPage, /if \(!canManageProjectPermissions\) return;/);
  assert.match(importPage, /listProjectMembers\(apiFetch, params\.id\)/);
  assert.match(api, /searchProjectMemberCandidates\(apiFetch: ApiFetch, projectId: string, query: string, signal\?: AbortSignal\)/);
  assert.match(importPage, /useDebouncedProjectMemberCandidateSearch/);
  assert.match(importPage, /searchProjectMemberCandidates\(apiFetch, params\.id, query, signal\)/);
  assert.doesNotMatch(importPage, /listUsers\(apiFetch, "project_members"\)/);
  assert.match(importPage, /replaceProjectMember\(apiFetch, params\.id, userId/);
  assert.match(importPage, /removeProjectMember\(apiFetch, params\.id, userId, project\.lock_version\)/);
  assert.match(importPage, /canManageProjectPermissions \? <button className="action-button secondary" onClick=\{openPermissionModal\}/);
  assert.match(importPage, /permissionModalOpen && canManageProjectPermissions \? \(/);
  assert.match(importPage, /project-permission-modal/);
  assert.match(importPage, /projectImportPermissionOwnerOnly/);
  assert.match(importPage, /ProjectMemberAutocomplete/);
  assert.match(memberAutocomplete, /project-permission-search-field/);
  assert.match(memberAutocomplete, /role="combobox"/);
  assert.match(memberAutocomplete, /role="listbox"/);
  assert.match(memberAutocomplete, /role="option"/);
  assert.match(importPage, /pendingPermissionUsers/);
  assert.match(importPage, /stagePermissionCandidate/);
  assert.match(importPage, /commitPendingPermissionCandidates/);
  assert.match(importPage, /project-permission-selected-users/);
  assert.match(importPage, /onSelect=\{stagePermissionCandidate\}/);
  assert.doesNotMatch(importPage, /<Search size=\{16\} \/>/);
  assert.doesNotMatch(importPage, /,\s*Search,\s*/);
  assert.doesNotMatch(importPage, /<datalist/);
  assert.doesNotMatch(importPage, /selectedPermissionUser/);
  assert.match(importPage, /projectMemberOwnerProtection\(member, projectMembers, currentUser\?\.user_id\)/);
  assert.match(importPage, /protection \? null : <button className="icon-button danger"/);
  assert.match(importPage, /disabled=\{!canManageProjectPermissions \|\| busy \|\| Boolean\(protection\)\}/);
  assert.match(importPage, /projectImportPermissionSearchMissingAccess/);
  assert.match(importPage, /projectImportLastOwnerProtected/);
  assert.match(importPage, /projectImportSelfOwnerProtected/);
  assert.doesNotMatch(importPage, /project-permission-candidates/);
  assert.match(css, /\.project-permission-modal/);
  assert.match(css, /\.project-permission-member/);
  assert.match(css, /\.project-permission-autocomplete\s*\{[\s\S]*left:\s*0/);
  assert.match(css, /\.project-permission-autocomplete\s*\{[\s\S]*right:\s*0/);
  assert.match(css, /\.project-permission-autocomplete button\s*\{[\s\S]*min-height:\s*var\(--project-permission-option-height\)/);
  assert.match(css, /max-height:\s*calc\(\(var\(--project-permission-option-height\) \* 5\) \+ 2px\)/);
  assert.match(css, /\.project-permission-autocomplete\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(css, /\.project-permission-selected-users\s*\{[\s\S]*flex-wrap:\s*wrap/);
  assert.match(css, /\.project-permission-selected-user\s*\{[\s\S]*border-radius:\s*999px/);
  assert.doesNotMatch(css, /\.project-permission-candidates/);
  assert.match(css, /\.project-permission-member-list\s*\{[\s\S]*height:\s*196px/);
  assert.match(css, /\.project-permission-member-list\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.equal(zh.projectImportPermissionManagement, "權限管理");
  assert.equal(en.projectImportPermissionManagement, "Permission Management");
  assert.equal(zh.projectImportRemovePendingMember, "移除待加入成員");
  assert.equal(en.projectImportRemovePendingMember, "Remove pending member");
  assert.match(zh.projectImportPermissionSearchMissingAccess, /知識專案存取權/);
  assert.match(en.projectImportPermissionSearchMissingAccess, /Knowledge Projects access/);
  assert.match(zh.projectImportLastOwnerProtected, /最後一位 Owner/);
  assert.match(en.projectImportSelfOwnerProtected, /own Owner membership/);
  assert.match(zh.projectImportPermissionHelp, /至少保留一位 Owner/);
  assert.match(en.projectImportPermissionHelp, /at least one Owner/);
});

test("document import page uses live document upload APIs with OCR options", async () => {
  const [api, modal, importPage, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/KnowledgeSourceModals.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of ["listProjectDocuments", "uploadProjectDocuments", "startDocumentExtraction"]) assert.match(api, new RegExp(required));
  assert.match(api, /form\.append\("ocr_model_id"/);
  assert.match(api, /form\.append\("force_ocr", "true"\)/);
  assert.match(modal, /uploadOcrModel/);
  assert.match(modal, /uploadForceOcr/);
  assert.equal(zh.uploadOcrModel, "OCR 模型");
  assert.equal(en.uploadOcrModel, "OCR model");
  assert.match(importPage, /listModels\(apiFetch, "OCR"\)/);
  assert.match(importPage, /onUploadFiles=\{uploadLiveDocuments\}/);
  assert.match(api, /updateProjectDocumentFile/);
  const noChangeIndex = importPage.indexOf("if (response.no_change) {");
  const applyUpdatedIndex = importPage.indexOf("const next = await applyUpdatedDocument(response.document);", noChangeIndex);
  assert.ok(noChangeIndex > -1, "Update file no-change branch should be explicit");
  assert.ok(applyUpdatedIndex > noChangeIndex, "No-change branch should run before applying returned document state");
  const noChangeBranch = importPage.slice(noChangeIndex, applyUpdatedIndex);
  assert.match(noChangeBranch, /setVersionUpdateNotice\(t\("projectImportUpdateNoChange"\)\)/);
  assert.match(noChangeBranch, /return;/);
});

test("document import page uses live pipeline detail and retry APIs", async () => {
  const [api, importPage, modal, css, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/KnowledgeSourceModals.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of ["PipelineStepSummary", "PipelineRunDetail", "getPipelineDetail", "retryPipelineStep"]) assert.match(api, new RegExp(required));
  assert.match(importPage, /getPipelineDetail\(apiFetch/);
  assert.match(importPage, /retryPipelineStep\(apiFetch/);
  assert.match(importPage, /submission_ready/);
  assert.match(importPage, /projectImportPipelineStepDetails/);
  assert.match(importPage, /function pipelineStepLabel/);
  assert.match(importPage, /function pipelineStepStatusKind/);
  assert.match(importPage, /function pipelineStepStatusLabel/);
  assert.match(importPage, /function pipelineStepStats/);
  assert.match(importPage, /auto_tag:\s*"knowledgeDetailStepAutoTag"/);
  assert.match(importPage, /pipelineStepLabel\(pipelineCurrentStep, t\)/);
  assert.match(importPage, /pipelineStepLabel\(step\.name, t\)/);
  assert.match(importPage, /const stepStats = cardSteps\?\.length \? pipelineStepStats\(cardSteps\) : null/);
  assert.match(importPage, /className="pipeline-step-overview"/);
  assert.match(importPage, /projectImportPipelineStepOverviewAria/);
  assert.match(importPage, /projectImportPipelineStepProgress/);
  assert.match(importPage, /projectImportPipelineStepOverall/);
  assert.match(importPage, /className="pipeline-step-card-grid"/);
  assert.match(importPage, /className="pipeline-step-card-item"/);
  assert.match(importPage, /className=\{`pipeline-step-card step-\$\{statusKind\}`\}/);
  assert.match(importPage, /className="pipeline-step-number"/);
  assert.match(importPage, /className=\{`pipeline-step-status step-\$\{statusKind\}`\}/);
  assert.match(importPage, /className="pipeline-step-progress"/);
  assert.match(importPage, /projectImportPipelineStepPercentAria/);
  assert.match(importPage, /className="pipeline-step-artifact"/);
  assert.match(importPage, /className="pipeline-step-error"/);
  assert.match(importPage, /className="pipeline-step-arrow"/);
  assert.match(importPage, /aria-hidden="true"><ArrowRight size=\{16\}/);
  assert.doesNotMatch(importPage, /<span>\{step\.name\.replaceAll\("_", " "\)\}<\/span>/);
  assert.doesNotMatch(importPage, /pipeline-step-chip/);
  assert.doesNotMatch(importPage, /className=\{`pipeline-step-row/);
  assert.match(css, /\.pipeline-step-overview/);
  assert.match(css, /\.pipeline-step-card-grid/);
  assert.match(css, /\.pipeline-step-card/);
  assert.match(css, /\.pipeline-step-card\.step-completed/);
  assert.match(css, /\.pipeline-step-card\.step-running/);
  assert.match(css, /\.pipeline-step-card\.step-waiting/);
  assert.match(css, /\.pipeline-step-card\.step-failed/);
  assert.match(css, /\.pipeline-step-progress/);
  assert.match(css, /\.pipeline-step-artifact/);
  assert.match(css, /\.pipeline-step-error/);
  assert.match(css, /\.pipeline-step-arrow/);
  assert.match(modal, /CANONICAL_UPLOAD_PIPELINE_STEPS/);
  assert.match(modal, /progressDetailsOpen/);
  assert.match(modal, /liveProgressDocuments/);
  assert.match(modal, /localUploadProgressSteps/);
  assert.match(modal, /waitingPipelineSteps/);
  assert.match(modal, /upload-progress-detail-toggle/);
  assert.match(modal, /upload-progress-detail-panel/);
  assert.match(modal, /upload-progress-step-list/);
  assert.match(modal, /uploadProgressShowDetails/);
  assert.match(modal, /uploadProgressHideDetails/);
  assert.match(modal, /uploadProgressStepCount/);
  assert.match(modal, /uploadProgressWaitingLivePipeline/);
  assert.match(importPage, /onProgressDocuments\?\.\(summaries\)/);
  assert.match(importPage, /getPipelineDetail\(apiFetch, params\.id, result\.document\.id, versionId, pipelineId\)/);
  assert.match(css, /\.upload-progress-detail-toggle/);
  assert.match(css, /\.upload-progress-detail-panel/);
  assert.match(css, /\.upload-progress-step-list/);
  assert.match(css, /\.upload-progress-step\.step-running/);
  assert.equal(zh.projectImportPipelineStepDetails, "Pipeline step 明細 · Staging / Development adapter");
  assert.equal(en.projectImportPipelineStepDetails, "Pipeline step details · Staging / Development adapter");
  assert.equal(zh.projectImportStepStatusCompleted, "已完成");
  assert.equal(en.projectImportStepStatusCompleted, "Completed");
  assert.equal(zh.projectImportStepStatusFailed, "失敗");
  assert.equal(en.projectImportStepStatusFailed, "Failed");
  assert.equal(zh.uploadProgressShowDetails, "展開處理細節");
  assert.equal(en.uploadProgressShowDetails, "Show processing details");
  assert.equal(zh.uploadProgressWaitingLivePipeline, "等待 Backend 回傳 live Pipeline 明細");
  assert.equal(en.uploadProgressWaitingLivePipeline, "Waiting for live Pipeline details from the backend");
  assert.equal(zh.projectImportRetryCount, "重試 {count}/3");
  assert.equal(zh.statusActive, "啟用");
  assert.equal(zh.knowledgeDetailStepAutoTag, "AI自動貼標");
  assert.equal(en.knowledgeDetailStepAutoTag, "AI auto tagging");
  assert.match(importPage, /retryCount/);
  assert.match(modal, /steps\?: Array/);
});

test("document import pipeline UI exposes publish-stage states and action links", async () => {
  const [importPage, pipelineList, shell, zh, en] = await Promise.all([
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/PipelineList.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const status of ["pending_manager_review", "pending_owner_review", "publish_ready", "publishing", "production_indexing", "graph_syncing", "published_active"]) {
    assert.match(importPage, new RegExp(status));
    assert.match(pipelineList, new RegExp(status));
  }
  for (const key of ["statusProductionIndexing", "statusGraphSyncing", "statusPublishedActive", "projectImportOpenApprovalWorkspace", "projectImportOpenChatTest"]) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
  }
  for (const key of ["statusProductionIndexing", "statusGraphSyncing", "statusPublishedActive"]) {
    assert.match(shell, new RegExp(key));
  }
  assert.match(importPage, /projectImportOpenApprovalWorkspace/);
  assert.match(importPage, /projectImportOpenChatTest/);
  assert.match(importPage, /publishStageAction/);
  assert.match(importPage, /projectImportWaitingManager/);
  assert.match(importPage, /projectImportWaitingOwner/);
  assert.match(importPage, /projectImportWaitingPublisher/);
});

test("system management reads live APIs and keeps safe save boundaries", async () => {
  const [source, css] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8")
  ]);
  for (const required of ["listUsers(apiFetch)", "listRoles(apiFetch)", "listModels(apiFetch)", "getSystemParameters(apiFetch)", "getIdentitySettings(apiFetch)", "getSystemStatus(apiFetch)", "listExternalGroups(apiFetch)", "listExternalGroupMappings(apiFetch)"]) assert.match(source, new RegExp(required.replace(/[()]/g, "\\$&")));
  assert.match(source, /replacePermissions\(apiFetch/);
  assert.match(source, /updateSystemParameters\(apiFetch/);
  assert.match(source, /systemStatus\.dependencies/);
  assert.match(source, /systemStatus\.providers/);
  assert.match(source, /systemStatus\.recent_errors/);
  assert.match(source, /systemStatus\.worker/);
  assert.match(source, /disabled=\{!canEditPermissions \|\| selectedRoleReadOnly\}/);
  assert.match(source, /disabled=\{!canEditParameters\}/);
  assert.match(css, /\.system-detail-grid > div\s*\{[^}]*display: grid;[^}]*gap: 4px;/s);
  assert.match(css, /\.system-detail-grid strong\s*\{[^}]*overflow-wrap: anywhere;/s);
});

test("system management manual role users are searchable with visible draft membership states", async () => {
  const [source, css, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(source, /const \[roleUserDraftIds, setRoleUserDraftIds\] = useState<string\[\]>\(\[\]\)/);
  assert.match(source, /const \[roleUserSearch, setRoleUserSearch\] = useState\(""\)/);
  assert.match(source, /user\.raw\?\.employee_id/);
  assert.match(source, /user\.raw\?\.keycloak_user_id/);
  assert.match(source, /roleUserSearchText\(user\)\.includes\(roleUserSearchTerm\)/);
  assert.match(source, /pendingAddUsers/);
  assert.match(source, /pendingRemoveUsers/);
  assert.match(source, /systemRoleUserPendingAdd/);
  assert.match(source, /systemRoleUserPendingRemove/);
  assert.match(source, /systemRoleUserLdapMember/);
  assert.match(source, /systemRoleUserBreakGlassMember/);
  assert.match(source, /systemRoleUserManualMember/);
  assert.match(source, /const isRetained = isExternal \|\| isBreakGlass/);
  assert.match(source, /const checked = isManualDraftMember \|\| isRetained/);
  assert.match(source, /disabled=\{!canEditRoles \|\| modal\.role\.isActive === false \|\| submitting \|\| isRetained\}/);
  assert.match(source, /replaceRoleUsers\(apiFetch, modal\.role\.id, \{ lock_version: roleUsers\.lock_version, user_ids: roleUserDraftIds \}\)/);
  assert.match(source, /className="system-crud-form role-user-editor"/);
  assert.match(source, /modal\.type === "role-users" \? " role-user-modal"/);
  assert.match(source, /className="role-user-draft-summary"/);
  assert.match(css, /\.role-user-modal\s*\{[^}]*height: min\(86vh, 820px\);[^}]*height: min\(86dvh, 820px\);/s);
  assert.match(css, /\.role-user-modal > \.role-user-editor\s*\{[^}]*display: flex;[^}]*flex: 1 1 auto;[^}]*flex-direction: column;[^}]*min-height: 0;[^}]*overflow-y: auto;/s);
  assert.match(css, /\.role-user-modal > \.role-user-editor > footer\s*\{[^}]*margin-top: auto;/s);
  assert.match(css, /\.role-user-picker-row input\[type="checkbox"\]\s*\{[^}]*width: 18px;[^}]*min-height: 18px;/s);
  assert.match(css, /\.role-user-summary-metrics\s*\{[^}]*grid-template-columns: repeat\(5, minmax\(0, 1fr\)\);/s);
  assert.match(css, /\.role-user-picker-row\.external-retained/s);
  assert.match(css, /\.role-user-source-badges/s);
  for (const key of [
    "systemRoleUserSearch",
    "systemRoleUserSearchPlaceholder",
    "systemRoleUserDraftSummary",
    "systemRoleUserPendingAdd",
    "systemRoleUserPendingRemove",
    "systemRoleUserLdapMember",
    "systemRoleUserBreakGlassMember",
    "systemRoleUserManualMember",
    "systemRoleUserNoSearchResults",
    "systemEmployeeIdValue"
  ]) {
    assert.ok(zh[key], `missing zh key ${key}`);
    assert.ok(en[key], `missing en key ${key}`);
  }
});

test("system management exposes live completion actions for users roles models and identity", async () => {
  const [api, source, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  for (const helper of [
    "updateUser",
    "updateUserStatus",
    "createRole",
    "updateRole",
    "deleteRole",
    "replaceRoleUsers",
    "setRoleExternalGroupMapping",
    "createModel",
    "updateModel",
    "deleteModel",
    "setDefaultModel",
    "testModel",
    "startIdentityReauth",
    "completeIdentityReauth",
    "lockIdentitySettings",
    "validateIdentitySettingsCandidate",
    "activateIdentitySettings",
    "queueIdentitySync",
    "listIdentitySyncRuns",
    "getSystemStatus"
  ]) assert.match(api, new RegExp(`export async function ${helper}`));

  for (const usage of [
    "updateUser(apiFetch",
    "updateUserStatus(apiFetch",
    "createRole(apiFetch",
    "updateRole(apiFetch",
    "deleteRole(apiFetch",
    "replaceRoleUsers(apiFetch",
    "setRoleExternalGroupMapping(apiFetch",
    "createModel(apiFetch",
    "updateModel(apiFetch",
    "deleteModel(apiFetch",
    "setDefaultModel(apiFetch",
    "testModel(apiFetch",
    "startIdentityReauth(apiFetch",
    "completeIdentityReauth(apiFetch",
    "lockIdentitySettingsApi(apiFetch",
    "validateIdentitySettingsCandidate(apiFetch",
    "activateIdentitySettings(apiFetch",
    "queueIdentitySync(apiFetch",
    "listIdentitySyncRuns(apiFetch"
  ]) assert.match(source, new RegExp(usage.replace(/[()]/g, "\\$&")));

  assert.match(source, /replaceSystemRoute\("identity", "pending"\)/);
  assert.match(source, /window\.location\.assign\(flow\.authorization_url\)/);
  assert.match(source, /completeIdentityReauth\(apiFetch\)/);
  assert.doesNotMatch(source, /window\.open|postMessage|identityReauthPopupRef/);
  assert.doesNotMatch(source, /completeFixtureReauthentication|identityReauthFixtureWarning|identity-fixture-banner/);

  assert.match(source, /disabled=\{!canCreateRoles\}/);
  assert.match(source, /disabled=\{!canCreateModels\}/);
  assert.match(source, /api_key_configured/);
  assert.match(source, /function activateModel\(model: ModelRow\)/);
  assert.match(source, /updateModel\(apiFetch, model\.id, \{ is_active: true \}\)/);
  assert.match(source, /modelIsActive \? <button[\s\S]*t\("systemDisable"\)[\s\S]*<button className="icon-text-button" disabled=\{!canEditModels\}[\s\S]*t\("systemEnable"\)/);
  assert.match(source, /systemRoleDeleted/);
  assert.match(source, /systemRoleDisabledMessage/);
  assert.match(source, /systemModelDeactivated/);
  assert.match(source, /systemModelDeleted/);
  assert.equal(zh.systemRoleDeleted, "{name} 已刪除並從角色管理中移除。");
  assert.equal(en.systemRoleDeleted, "{name} was deleted and removed from role management.");
  assert.equal(zh.systemModelDeactivated, "模型已停用。");
  assert.equal(en.systemModelDeactivated, "Model disabled.");
});

test("CHG-233 separates local roles from LDAP groups and uses role-scoped one-to-one mapping", async () => {
  const [api, source, css, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(api, /`\/roles\/\$\{roleId\}\/external-group-mapping`/);
  assert.doesNotMatch(api, /replaceExternalGroupMappings/);
  assert.match(source, /const \[rolesView, setRolesView\] = useState<"local" \| "ldap">\("local"\)/);
  assert.match(source, /externalGroups\.filter\(\(group\) => group\.identity_origin === "ldap"\)/);
  assert.match(source, /!group\.mapped_role_id \|\| group\.mapped_role_id === mappingRole\?\.id/);
  assert.match(source, /role\.isSystem \? <div className="system-role-card-badges"><StateBadge tone="gold">/);
  assert.match(source, /!role\.isSystem && canDeleteRoles/);
  assert.match(source, /modal\.role\?\.isSystem \? modal\.role\.name/);
  assert.match(source, /systemLdapReadOnly/);
  assert.match(css, /\.system-role-type-tabs/);
  assert.match(css, /\.system-role-grid\s*\{[^}]*repeat\(3, minmax\(0, 1fr\)\)/s);

  for (const key of [
    "systemLocalRoles",
    "systemLdapGroups",
    "systemProtectedDefaultRole",
    "systemSetMapping",
    "systemChangeOrRemoveMapping",
    "systemRoleMappingTitle",
    "systemOneToOneMappingHelp",
    "systemMappingImmediateHelp",
    "systemLdapReadOnly"
  ]) {
    assert.ok(zh[key], `missing zh key ${key}`);
    assert.ok(en[key], `missing en key ${key}`);
  }
});

test("system management AI model editor exposes provider-specific configuration fields", async () => {
  const [source, css, zh, en] = await Promise.all([
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  for (const provider of ["OpenAI", "Gemini", "Claude", "Ollama", "vLLM", "Custom"]) {
    assert.match(source, new RegExp(provider.replace(/[()]/g, "\\$&")));
  }

  for (const field of [
    "model_name",
    "base_url",
    "api_version",
    "anthropic_version",
    "organization_id",
    "project_id",
    "embedding_dimension",
    "timeout_seconds",
    "headers_json",
    "config_advanced",
    "api_key_secret_ref"
  ]) assert.match(source, new RegExp(field));

  assert.match(source, /modal\.model \? t\("systemSaveModel"\) : t\("systemAddModel"\)/);
  assert.match(source, /modal\.model \? <Save size=\{16\} \/> : <Plus size=\{16\} \/>/);
  assert.match(source, /providerNeedsCredential/);
  assert.match(source, /containsSecretConfigKey/);
  assert.match(source, /openai_compatible = true/);
  assert.match(source, /function pairedEmbeddingModelIds\(model: ModelRow \| undefined\)/);
  assert.match(source, /const \[modelPairDraft, setModelPairDraft\] = useState<string\[\]>\(\[\]\)/);
  assert.match(source, /function toggleModelPair\(modelId: string, checked: boolean\)/);
  assert.match(source, /activeEmbeddingModels = liveModels\.filter/);
  assert.match(source, /formData\.getAll\("paired_embedding_model_ids"\)/);
  assert.match(source, /config\.paired_embedding_model_ids = pairedIds/);
  assert.match(source, /delete config\.paired_embedding_model_ids/);
  assert.match(source, /modelTypeDraft === "Chat"/);
  assert.match(source, /<details className="system-model-pair-dropdown">/);
  assert.match(source, /format\("systemChatEmbeddingPairsSelected", \{ count: modelPairDraft\.length \}\)/);
  assert.match(source, /systemChatEmbeddingPairs/);
  assert.match(source, /systemChatModelPairRequired/);
  assert.match(zh.systemAdvancedConfigHelp, /max_tokens/);
  assert.match(en.systemAdvancedConfigHelp, /max_tokens/);
  assert.equal(zh.systemChatEmbeddingPairs, "對應向量模型");
  assert.equal(en.systemChatEmbeddingPairs, "Paired Embedding models");
  assert.equal(zh.systemChatEmbeddingPairsPlaceholder, "選擇對應向量模型");
  assert.equal(en.systemChatEmbeddingPairsPlaceholder, "Select paired Embedding models");
  assert.match(zh.systemChatModelPairRequired, /至少需要選擇/);
  assert.match(en.systemChatModelPairRequired, /Select at least one/);
  assert.match(css, /\.system-model-pairing/);
  assert.match(css, /\.system-model-pair-dropdown summary/);
  assert.match(css, /\.system-model-pair-list/);
  assert.match(css, /\.system-crud-modal[\s\S]*overflow: hidden/);
  assert.match(css, /\.system-crud-form[\s\S]*overflow-y: auto/);
  assert.match(css, /\.system-crud-form footer[\s\S]*position: sticky/);
});

test("reports page exposes explicit live queries, authorized filters, pagination and per-report CSV", async () => {
  const [source, api] = await Promise.all([
    readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8")
  ]);

  for (const required of [
    "overview",
    "projects",
    "references",
    "documents",
    "quality",
    "models",
    "alerts",
    "applyQuery",
    "downloadTopic",
    "getReportFilterOptions",
    "getReportSummary(apiFetch",
    "downloadReportCsv(apiFetch",
    "buildReportFilename",
    "normalizeReportCsvLocale",
    "ReportPagination",
    "REPORT_PAGE_SIZE = 20",
    "reportLiveData",
    "ReportEmptyState",
    "draftFilters",
    "appliedFilters"
  ]) assert.match(source, new RegExp(required.replace(/[()]/g, "\\$&")));
  for (const required of ["ReportSummaryResponse", "ReportFilterOptionsResponse", "getReportFilterOptions", "getReportSummary", "downloadReportCsv", "/reports/filter-options", "/reports/summary", "/reports/export.csv"]) assert.match(api, new RegExp(required.replace(/[()]/g, "\\$&")));
});

test("approval workflow uses live review publish APIs", async () => {
  const [api, workspace, detail, submit, zh, en, css] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/approve/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/approve/[approvalTaskId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/submit-review/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8")
  ]);
  for (const required of [
    "getApprovalSummary",
    "listPendingApprovals",
    "listMyApprovalSubmissions",
    "listPendingPublishApprovals",
    "getApprovalTask",
    "ApprovalPendingPublishResponse",
    "ApprovalChunkEvidence",
    "ApprovalChatEvidence",
    "latest_version_id",
    "evidence_stale",
    "read_only",
    "read_only_reason",
    "approveApprovalTask",
    "rejectApprovalTask",
    "publishDocumentVersion",
    "submitDocumentVersionReview",
    "Idempotency-Key"
  ]) assert.match(api, new RegExp(required.replace(/[()]/g, "\\$&")));
  for (const required of ["project_name", "document_title", "version_label", "submitter_given_name", "submitter_family_name", "submitter_name", "submitter_email"]) assert.match(api, new RegExp(required));
  assert.match(workspace, /const \{ apiFetch, authReady \} = useAuth\(\)/);
  assert.doesNotMatch(workspace, /canViewApprovalWorkspace/);
  assert.doesNotMatch(workspace, /canTrackOwnSubmissions/);
  assert.doesNotMatch(workspace, /canPublishDocuments/);
  assert.match(workspace, /getApprovalSummary\(apiFetch\)/);
  assert.match(workspace, /listPendingApprovals\(apiFetch\)/);
  assert.match(workspace, /listMyApprovalSubmissions\(apiFetch\)/);
  assert.match(workspace, /listPendingPublishApprovals\(apiFetch\)/);
  assert.match(workspace, /getApprovalSummary\(apiFetch\)/);
  assert.match(workspace, /listPendingApprovals\(apiFetch\)/);
  assert.match(workspace, /pendingPublish/);
  assert.match(workspace, /approvalPendingPublishPanel/);
  assert.match(workspace, /approvalOpenApprovalDetail/);
  assert.match(workspace, /approvalNoPendingPublish/);
  assert.match(workspace, /item\.approval_task_id/);
  assert.match(workspace, /publishDocumentVersion\(apiFetch, item\.document_version_id, \{ lock_version: item\.lock_version, impact_confirmed: true \}\)/);
  assert.match(workspace, /Loader2/);
  assert.match(workspace, /publishingThisVersion = publishingVersionId === item\.document_version_id/);
  assert.match(workspace, /aria-busy=\{publishingThisVersion\}/);
  assert.match(workspace, /role=\{publishingThisVersion \? "status" : undefined\}/);
  assert.match(workspace, /disabled=\{publishingThisVersion\}/);
  assert.match(workspace, /publishingThisVersion \? t\("approvalPublishing"\) : t\("publish"\)/);
  assert.match(workspace, /className="table-list approval-task-list"/);
  assert.match(workspace, /className="table-row approval-task-row"/);
  assert.match(workspace, /approval\.project_name/);
  assert.match(workspace, /approval\.document_title/);
  assert.match(workspace, /approval\.version_label/);
  assert.match(workspace, /displaySubmitterName\(approval, locale\)/);
  assert.match(workspace, /displaySubmitterDetail\(approval, t\)/);
  assert.match(workspace, /className="approval-workspace-stack"/);
  assert.equal((workspace.match(/<StatCard\b/g) ?? []).length, 3);
  for (const key of ["approvalPendingMine", "approvalMySubmissions", "approvalPublishControl"]) assert.match(workspace, new RegExp(key));
  assert.doesNotMatch(workspace, /Live API|approvalConnected|approvalLiveDataHelp/);
  assert.match(workspace, /className="page-grid approval-summary-grid"/);
  assert.match(workspace, /const \[loading, setLoading\] = useState\(true\)/);
  assert.match(workspace, /role="alert"/);
  assert.match(css, /\.approval-summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/s);
  assert.equal(zh.approvalConnected, undefined);
  assert.equal(en.approvalConnected, undefined);
  assert.equal(zh.approvalLiveDataHelp, undefined);
  assert.equal(en.approvalLiveDataHelp, undefined);
  assert.match(detail, /const \{ apiFetch \} = useAuth\(\)/);
  assert.match(detail, /getApprovalTask\(apiFetch, params\.approvalTaskId\)/);
  assert.match(detail, /liveDetail\.chunks/);
  assert.match(detail, /liveDetail\.chat_records/);
  assert.match(detail, /readOnlyReasonLabel/);
  assert.match(detail, /sourceLabelFromMapping/);
  assert.match(detail, /approvalReadOnlyEvidence/);
  assert.match(detail, /approvalEvidenceStale/);
  assert.match(detail, /disabled=\{!canDecide\}/);
  assert.match(detail, /displayConversations/);
  assert.match(detail, /approveApprovalTask\(apiFetch/);
  assert.match(detail, /rejectApprovalTask\(apiFetch/);
  assert.match(detail, /publishDocumentVersion\(apiFetch/);
  assert.match(detail, /Loader2/);
  assert.match(detail, /const \[publishingVersion, setPublishingVersion\] = useState\(false\)/);
  assert.match(detail, /const \[publishError, setPublishError\] = useState<string \| null>\(null\)/);
  assert.match(detail, /const canPublish = !submittingDecision && !publishingVersion && liveDetail\?\.version\.status === "approved"/);
  assert.doesNotMatch(detail, /const canPublish = !submittingDecision && !readOnly && liveDetail\?\.version\.status === "approved"/);
  assert.match(detail, /setPublishingVersion\(true\)/);
  assert.match(detail, /setPublishingVersion\(false\)/);
  assert.match(detail, /setPublishError\(operationalErrorMessage\(error, t, format, "approvalPublishFailed"\)\)/);
  assert.match(detail, /aria-busy=\{publishingVersion\}/);
  assert.match(detail, /className="approval-decision-stack"/);
  assert.match(detail, /role=\{publishingVersion \? "status" : undefined\}/);
  assert.match(detail, /publishingVersion \? t\("approvalPublishing"\) : t\("publish"\)/);
  assert.match(detail, /import \{ useParams, useRouter \} from "next\/navigation"/);
  assert.match(detail, /type DecisionOutcome = \{ kind: "success" \| "error"/);
  assert.match(detail, /function approvalDecisionSuccessOutcome/);
  assert.match(detail, /stage === "owner_review"/);
  assert.match(detail, /approvalOwnerApproveSubmitted/);
  assert.match(detail, /approvalOwnerApproveNextStep/);
  assert.match(detail, /approvalManagerApproveSubmitted/);
  assert.match(detail, /approvalManagerApproveNextStep/);
  assert.match(detail, /approvalRejectNextStep/);
  assert.match(detail, /window\.setTimeout\(\(\) => \{\s*router\.push\("\/approve"\);?\s*\}, 1800\)/s);
  assert.match(detail, /const submittedDecision = decision/);
  assert.match(detail, /const submittedStage = liveDetail\.task\.review_stage/);
  assert.match(detail, /setDecisionOutcome\(approvalDecisionSuccessOutcome\(submittedDecision, submittedStage, t\)\)/);
  assert.match(detail, /setDecisionOutcome\(\{ kind: "error", title: t\("approvalDecisionFailed"\)/);
  assert.match(detail, /decisionOutcome\?\.kind !== "success"/);
  assert.match(submit, /submitDocumentVersionReview\(apiFetch/);
  assert.match(submit, /const \{ apiFetch, authReady \} = useAuth\(\)/);
  assert.match(submit, /getDocumentVersionSubmissionEvidence\(apiFetch, params\.id, loaded\.document\.id, loaded\.version\.id\)/);
  assert.match(submit, /evidence\?\.can_submit_review && evidence\.next_stage_allowed/);
  assert.doesNotMatch(submit, /listProjectMembers\(apiFetch, params\.id\)/);
  assert.doesNotMatch(submit, /can\("Document", "DocumentReview", "create"\)/);
  assert.match(submit, /submitReviewPermissionDenied/);
  assert.match(submit, /!evidence\?\.can_submit_review \? <small className="field-error">\{t\("submitReviewPermissionDenied"\)\}<\/small> : null/);
  assert.match(submit, /evidence && !evidence\.next_stage_allowed \? <small className="field-error">\{localizedBlockReasons\.join\(", "\)\}<\/small> : null/);
  assert.match(submit, /disabled=\{submitting \|\| !detail \|\| !canSubmitReview\}/);
  assert.match(submit, /type ApprovalRequestResponse/);
  assert.match(submit, /useState<ApprovalRequestResponse \| null>\(null\)/);
  assert.match(submit, /const response = await submitDocumentVersionReview\(apiFetch/);
  assert.match(submit, /setSubmissionResult\(response\)/);
  assert.match(submit, /submissionResult\.current_task_id/);
  assert.match(submit, /submitReviewNextStageManagerReview/);
  assert.match(submit, /submitReviewRedirectingToWorkspace/);
  assert.match(submit, /window\.setTimeout\(\(\) => \{\s*router\.push\("\/approve"\);?\s*\}, 1800\)/s);
  assert.doesNotMatch(submit, /setSubmitted/);
  assert.doesNotMatch(submit, /submitReviewBackToProject/);
  assert.doesNotMatch(submit, /router\.push\(`\/project\/\$\{params\.id\}\/import`\)/);
  for (const key of ["approvalReadOnlyEvidence", "approvalEvidenceStaleReason", "approvalTaskCompletedReason", "approvalEvidenceFreshness", "approvalEvidenceCurrent", "approvalSubmitter"]) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
  }
  for (const key of ["approvalManagerApproveSubmitted", "approvalManagerApproveNextStep", "approvalOwnerApproveSubmitted", "approvalOwnerApproveNextStep", "approvalRejectNextStep"]) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
  }
  for (const key of ["approvalPendingPublishPanel", "approvalOpenApprovalDetail", "approvalNoPendingPublish", "approvalApprovedTimeUnknown", "approvalSubmitterUnknown", "approvalPublishing"]) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
  }
  for (const key of ["submitReviewNextStageLabel", "submitReviewNextStageManagerReview", "submitReviewTaskIdLabel", "submitReviewDocumentVersionLabel", "submitReviewRequestStatusLabel", "submitReviewRedirectingToWorkspace"]) {
    assert.equal(typeof zh[key], "string");
    assert.equal(typeof en[key], "string");
  }
  assert.match(css, /\.approval-workspace-stack\s*\{[^}]*gap:\s*16px;/s);
  assert.match(css, /\.approval-task-row\s*\{[^}]*grid-template-columns:\s*minmax\(300px, 1\.25fr\)/s);
  assert.match(css, /\.approval-row-meta strong\s*\{[^}]*text-overflow:\s*ellipsis;/s);
  assert.match(css, /\.approval-decision-stack\s*\{[^}]*flex-wrap:\s*wrap;/s);
  assert.match(css, /\.spin\s*\{[^}]*animation:\s*source-spin 900ms linear infinite;/s);
  assert.match(css, /\.approval-result small\s*\{[^}]*font-size:\s*12px;/s);
  assert.match(css, /\.submission-success-detail\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/s);
  assert.match(css, /\.submission-redirect-note\s*\{[^}]*color:\s*var\(--deep-green\);/s);
  assert.match(zh.submitReviewPermissionDenied, /Owner|Editor/);
  assert.match(en.submitReviewPermissionDenied, /Owner or Editor/);
  assert.match(zh.submitReviewGoToApprovalCenter, /簽核工作台/);
  assert.match(en.submitReviewGoToApprovalCenter, /Approval Workspace/);
});

test("Milestone 15A protected routes do not render fixture fallback evidence", async () => {
  const [api, importPage, knowledgePage, approvalDetail, evidenceViewer, documentLayoutViewer, css, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/approve/[approvalTaskId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ApprovalEvidenceViewer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/DocumentLayoutViewer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  for (const source of [importPage, knowledgePage, approvalDetail, evidenceViewer]) {
    assert.doesNotMatch(source, /展示資料/);
    assert.doesNotMatch(source, /信用風險模型治理規範/);
    assert.doesNotMatch(source, /risk-model-governance-review/);
  }

  assert.doesNotMatch(approvalDetail, /@\/lib\/fixtures/);
  assert.doesNotMatch(evidenceViewer, /@\/lib\/fixtures/);
  assert.match(importPage, /projectImportNoFormalDocuments/);
  assert.match(zh.projectImportNoFormalDocuments, /目前沒有符合條件的正式文件/);
  assert.match(en.projectImportNoFormalDocuments, /No matching formal documents/);
  assert.match(api, /source_text: string \| null/);
  assert.match(api, /markdown_text: string \| null/);
  assert.match(api, /markdown_artifact_status: "available" \| "processing" \| "missing" \| "failed" \| "invalid"/);
  assert.match(api, /markdown_artifact_reason_code: string \| null/);
  assert.match(api, /original_file: OriginalFileViewerMetadata \| null/);
  assert.match(api, /document_layout: DocumentLayoutArtifact \| null/);
  assert.match(api, /source_mapping_available: boolean/);
  assert.match(api, /markdown_available_count: number/);
  assert.match(api, /missing_markdown_count: number/);
  assert.match(api, /KnowledgeTagResponse/);
  assert.match(api, /tag_details: KnowledgeTagResponse\[\]/);
  assert.match(api, /document_tags: KnowledgeTagResponse\[\]/);
  assert.match(api, /getKnowledgeArtifactBlob/);
  for (const required of [
    "createManualChunk",
    "addChunkTag",
    "deleteChunkTag",
    "autoTagChunk",
    "addDocumentTag",
    "deleteDocumentTag",
    "autoTagDocument"
  ]) assert.match(api, new RegExp(required));
  assert.doesNotMatch(knowledgePage, /isPdfLikeViewer/);
  assert.doesNotMatch(knowledgePage, /pdf-original-viewer/);
  assert.doesNotMatch(knowledgePage, /<iframe/);
  assert.match(knowledgePage, /DocumentLayoutViewer/);
  assert.match(knowledgePage, /liveDetail\?\.document_layout\?\.pages/);
  assert.match(knowledgePage, /isMarkdownOriginal\(liveDetail\?\.original_file\)/);
  assert.match(knowledgePage, /MarkdownRendered source=\{originalSourceText\}/);
  assert.doesNotMatch(knowledgePage, /return chunks\.map\(\(chunk\) => \(\{ id: chunk\.sourceAnchor/);
  assert.match(knowledgePage, /knowledgeDetailLayoutUnavailable/);
  assert.match(knowledgePage, /LayoutPipelineFallback/);
  assert.match(knowledgePage, /isPipelineActive/);
  assert.match(knowledgePage, /retryPipelineStep\(apiFetch/);
  assert.match(knowledgePage, /knowledgeDetailPipelineGeneratingLayout/);
  assert.match(knowledgePage, /knowledgeDetailRetryFailedStep/);
  assert.match(knowledgePage, /role="progressbar"/);
  assert.match(knowledgePage, /CanonicalMarkdownSource/);
  assert.match(knowledgePage, /selectMarkdownChunks/);
  assert.doesNotMatch(knowledgePage, /function markdownBlocks/);
  assert.match(knowledgePage, /knowledgeDetailDownloadOriginal/);
  assert.match(approvalDetail, /sourceAnchorFromMapping/);
  assert.match(approvalDetail, /id: chunk\.id/);
  assert.match(approvalDetail, /index: chunk\.chunk_index/);
  assert.match(approvalDetail, /documentLayout=\{liveDetail\?\.document_layout \?\? null\}/);
  assert.match(approvalDetail, /markdownText=\{liveDetail\?\.markdown_text \?\? null\}/);
  assert.match(approvalDetail, /originalFile=\{liveDetail\?\.original_file \?\? null\}/);
  assert.match(approvalDetail, /sourceText=\{liveDetail\?\.source_text \?\? null\}/);
  assert.match(approvalDetail, /documentTags=\{liveDetail\?\.document_tags \?\? \[\]\}/);
  assert.match(evidenceViewer, /SafeMarkdown/);
  assert.match(evidenceViewer, /DocumentLayoutViewer/);
  assert.match(documentLayoutViewer, /SafeMarkdownInline/);
  assert.match(documentLayoutViewer, /LayoutBlockView/);
  assert.match(evidenceViewer, /documentLayout\?\.pages\.length/);
  assert.match(evidenceViewer, /className="chunk-title-row"/);
  assert.match(evidenceViewer, /className="chunk-index-badge">#\{chunk\.index/);
  assert.match(evidenceViewer, /className="chunk-technical-id">\{chunk\.id\}/);
  assert.match(evidenceViewer, /className="chunk-content-shell"/);
  assert.match(evidenceViewer, /className="chunk-safe-markdown"/);
  assert.match(evidenceViewer, /knowledge-tag-editor readonly/);
  assert.match(evidenceViewer, /tag-source-\$\{tag\.source\}/);
  assert.match(evidenceViewer, /toggleSingleChunkSelection/);
  assert.match(evidenceViewer, /chunkIdsForResolvedSourceAnchor/);
  assert.match(documentLayoutViewer, /source-active/);
  assert.match(evidenceViewer, /layoutStatusLabel/);
  assert.match(evidenceViewer, /CanonicalMarkdownSource/);
  assert.match(evidenceViewer, /selectMarkdownChunks/);
  assert.doesNotMatch(evidenceViewer, /function markdownBlocks/);
  assert.doesNotMatch(evidenceViewer, /createManualChunk/);
  assert.doesNotMatch(evidenceViewer, /addChunkTag/);
  assert.doesNotMatch(evidenceViewer, /deleteChunkTag/);
  assert.doesNotMatch(evidenceViewer, /autoTagChunk/);
  assert.doesNotMatch(evidenceViewer, /knowledge-tag-add-button/);
  assert.doesNotMatch(evidenceViewer, /knowledge-tag-auto-button/);
  assert.doesNotMatch(evidenceViewer, /<strong>\{chunk\.id\} · \{chunk\.title\}<\/strong>/);
  const documentGraphPreview = await readFile(new URL("../../frontend/src/components/DocumentGraphPreview.tsx", import.meta.url), "utf8");
  const projectGraphPreview = await readFile(new URL("../../frontend/src/components/ProjectGraphPreview.tsx", import.meta.url), "utf8");
  const graphExplorer = await readFile(new URL("../../frontend/src/components/GraphExplorer.tsx", import.meta.url), "utf8");
  assert.match(documentGraphPreview, /import \{ GraphExplorer, type GraphExplorerEdge, type GraphExplorerNode \}/);
  assert.match(projectGraphPreview, /import \{ GraphExplorer, type GraphExplorerEdge, type GraphExplorerNode \}/);
  assert.match(documentGraphPreview, /graphChunks\.forEach/);
  assert.match(documentGraphPreview, /chunkNodeId\(chunk\.id\)/);
  assert.match(documentGraphPreview, /tagMap/);
  assert.match(documentGraphPreview, /documentTags\.forEach/);
  assert.match(documentGraphPreview, /statusLabel=\{format\("graphExplorerDocumentStatus"/);
  assert.match(documentGraphPreview, /DOCUMENT_CENTER/);
  assert.match(documentGraphPreview, /arcAngle\(index, graphChunks\.length\)/);
  assert.match(documentGraphPreview, /label: t\("graphRelationChunked"\)/);
  assert.match(projectGraphPreview, /function buildProjectExplorerGraph/);
  assert.match(projectGraphPreview, /getProjectGraph\(apiFetch, projectId, 120\)/);
  assert.match(projectGraphPreview, /getProjectGraphNeighbors/);
  assert.doesNotMatch(projectGraphPreview, /getKnowledgeGraphNeighbors/);
  assert.match(projectGraphPreview, /function mergeProjectGraphs/);
  assert.match(projectGraphPreview, /onNodeSelect=\{expandNeighborGraph\}/);
  assert.match(projectGraphPreview, /filter\(\(node\) => !node\.type\.toLowerCase\(\)\.includes\("version"\)\)/);
  assert.match(projectGraphPreview, /projectDocumentSources/);
  assert.doesNotMatch(projectGraphPreview, /versionDocumentIds/);
  assert.doesNotMatch(projectGraphPreview, /documentVersions/);
  assert.doesNotMatch(projectGraphPreview, /lower\.includes\("version"\)\) return "version"/);
  assert.doesNotMatch(projectGraphPreview, /type === "Document" \|\| type === "DocumentVersion"/);
  assert.match(projectGraphPreview, /const GRAPH_CENTER = \{ x: 540, y: 320 \}/);
  assert.match(projectGraphPreview, /function polarPoint/);
  assert.match(projectGraphPreview, /function sectorAngle/);
  assert.match(projectGraphPreview, /function sourceRelationshipLabel/);
  assert.match(projectGraphPreview, /graphRelationSourceUpload/);
  assert.match(projectGraphPreview, /graphRelationSourceFtp/);
  assert.match(projectGraphPreview, /graphRelationSourceSftp/);
  assert.match(projectGraphPreview, /graphRelationSourceFtps/);
  assert.match(projectGraphPreview, /graphRelationSourceSsh/);
  assert.match(projectGraphPreview, /graphRelationSourceS3/);
  assert.match(projectGraphPreview, /graphRelationSourceHttpApi/);
  assert.match(projectGraphPreview, /graphRelationSourceReferenceProject/);
  assert.match(projectGraphPreview, /relation: "source"/);
  assert.match(projectGraphPreview, /function compareChunks/);
  assert.match(projectGraphPreview, /function metadataContentType/);
  assert.match(projectGraphPreview, /documentNodes\.forEach/);
  assert.match(projectGraphPreview, /relatedChunks\.forEach/);
  assert.match(projectGraphPreview, /relatedTags\.forEach/);
  assert.match(projectGraphPreview, /Array\.from\(chunkLevelTagIds\)\.forEach/);
  assert.match(projectGraphPreview, /chunkGroupLabel: \(start, end, count\) => format\("graphChunkGroupLabel", \{ count, end, start \}\)/);
  assert.match(projectGraphPreview, /\.sort\(compareChunks\)/);
  assert.match(projectGraphPreview, /chunkTagIds\.get\(chunk\.id\)/);
  assert.match(projectGraphPreview, /\.\.\.polarPoint\(250, documentAngle, 0\.64\)/);
  assert.match(projectGraphPreview, /\.\.\.polarPoint\(410, chunkAngle, 0\.58\)/);
  assert.match(projectGraphPreview, /semanticLayer: 1/);
  assert.match(projectGraphPreview, /semanticLayer: 2/);
  assert.match(projectGraphPreview, /semanticLayer: 3/);
  assert.match(projectGraphPreview, /semanticLayer: 4/);
  assert.match(projectGraphPreview, /showLabel: false, source: node\.id, target: chunkNodeId/);
  assert.doesNotMatch(projectGraphPreview, /hideWhenParentSelectedId: node\.id/);
  assert.doesNotMatch(projectGraphPreview, /function radialChildPoint/);
  assert.match(projectGraphPreview, /graphProjectLiveStatus/);
  assert.equal(zh.graphChunkGroupLabel, "切片 {start}-{end}");
  assert.equal(en.graphChunkGroupLabel, "Chunks {start}-{end}");
  assert.equal(zh.graphChunkGroupDetail, "{count} 個切片");
  assert.equal(en.graphChunkGroupDetail, "{count} chunks");
  assert.equal(zh.graphGlobalLiveStatus, "{nodes} 個節點 · {edges} 個關聯");
  assert.equal(en.graphGlobalLiveStatus, "{nodes} nodes · {edges} edges");
  for (const graphSource of [documentGraphPreview, projectGraphPreview]) {
    assert.doesNotMatch(graphSource, /ProfessionalGraphNode/);
    assert.doesNotMatch(graphSource, /graphDisplay/);
    assert.doesNotMatch(graphSource, /buildProgressiveDisplayGraph/);
    assert.doesNotMatch(graphSource, /document-graph-node/);
    assert.doesNotMatch(graphSource, /graph-layer-switch/);
    assert.doesNotMatch(graphSource, /graph-detail-panel/);
  }
  assert.match(graphExplorer, /export type GraphExplorerNodeKind = "project" \| "document" \| "chunk" \| "tag" \| "group"/);
  assert.match(graphExplorer, /export type GraphExplorerSemanticLayer = 1 \| 2 \| 3 \| 4/);
  assert.match(graphExplorer, /function semanticZoomBand/);
  assert.match(graphExplorer, /if \(zoom >= 2\.5\) return "inspection"/);
  assert.match(graphExplorer, /if \(zoom >= 2\) return "tag"/);
  assert.match(graphExplorer, /if \(zoom >= 1\.5\) return "chunk"/);
  assert.match(graphExplorer, /function visualScaleForZoom/);
  assert.match(graphExplorer, /function nodeVisibilityAtZoom/);
  assert.match(graphExplorer, /data-graph-explorer="true"/);
  assert.match(graphExplorer, /data-graph-layout=\{layout\}/);
  assert.match(graphExplorer, /graph-explorer-layout-\$\{layout\}/);
  assert.match(graphExplorer, /function edgeLabelPosition/);
  assert.match(graphExplorer, /graph-explorer-edge-label/);
  assert.match(graphExplorer, /showLabel\?: boolean/);
  assert.match(graphExplorer, /onNodeSelect\?: \(nodeId: string\) => void/);
  assert.match(graphExplorer, /onNodeSelect\?\.\(node\.id\)/);
  assert.match(graphExplorer, /edge\.showLabel === false/);
  assert.match(graphExplorer, /focusParentId\?: string/);
  assert.match(graphExplorer, /hintUntilZoom\?: number/);
  assert.match(graphExplorer, /minZoom\?: number/);
  assert.match(graphExplorer, /revealAtZoom\?: number/);
  assert.match(graphExplorer, /semanticLayer\?: GraphExplorerSemanticLayer/);
  assert.match(graphExplorer, /hideWhenParentSelectedId\?: string/);
  assert.match(graphExplorer, /visibleNodes = useMemo/);
  assert.match(graphExplorer, /data-zoom-band=\{zoomBand\}/);
  assert.match(graphExplorer, /scale\(\$\{visualScale\}\)/);
  assert.match(graphExplorer, /node\.isHint \? " is-hint"/);
  assert.match(graphExplorer, /className="graph-explorer-toolbar"/);
  assert.match(graphExplorer, /className=\{`graph-explorer-canvas/);
  assert.match(graphExplorer, /className="graph-explorer-inspector"/);
  assert.match(graphExplorer, /data-graph-node-kind=\{node\.kind\}/);
  assert.match(graphExplorer, /data-semantic-layer=\{node\.semanticLayer\}/);
  assert.match(graphExplorer, /role="application"/);
  assert.match(graphExplorer, /role="button"[\s\S]*tabIndex=\{0\}/);
  assert.match(graphExplorer, /onKeyDown=\{\(event\) =>/);
  assert.match(graphExplorer, /setPointerCapture/);
  assert.match(graphExplorer, /onWheel=\{handleWheel\}/);
  assert.match(graphExplorer, /graphExplorerInspectorEmptyTitle/);
  assert.match(graphExplorer, /directNeighbors\(selectedNode\.id\)/);
  assert.match(knowledgePage, /className="chunk-technical-id"/);
  assert.match(knowledgePage, /className="chunk-title-meta"/);
  assert.match(knowledgePage, /className="chunk-inline-meta"/);
  assert.match(knowledgePage, /className="chunk-index-badge">#\{chunk\.index\}/);
  assert.match(knowledgePage, /<span>\{chunk\.sourceLabel\}<\/span>/);
  assert.match(knowledgePage, /knowledgeDetailTokenCount", \{ count: chunk\.tokens \}/);
  assert.match(knowledgePage, /knowledgeDetailConfidence", \{ value: Math\.round\(chunk\.confidence \* 100\) \}/);
  assert.match(knowledgePage, /className="chunk-content-shell"/);
  assert.doesNotMatch(knowledgePage, /className="chunk-meta"/);
  assert.match(knowledgePage, /knowledgeDetailSelectChunkAria", \{ id: chunk\.id, number: chunk\.index \}/);
  assert.doesNotMatch(knowledgePage, /<strong>\{chunk\.title\}<\/strong>/);
  assert.doesNotMatch(knowledgePage, /className="chunk-title-stack"/);
  const backendDocumentsRoute = await readFile(new URL("../../backend/app/api/routes/documents.py", import.meta.url), "utf8");
  const extractionPipeline = await readFile(new URL("../../backend/app/domain/extraction_pipeline.py", import.meta.url), "utf8");
  const backendModels = await readFile(new URL("../../backend/app/db/models.py", import.meta.url), "utf8");
  const llmTagDefaultMigration = await readFile(new URL("../../sql/migrations/V011__llm_chunk_tag_default.sql", import.meta.url), "utf8");
  assert.match(backendDocumentsRoute, /document=_project_document\(session, document, version, pipeline, expose_storage=False, visible_project_ids=set\(context\.visible_project_ids\), capabilities=project_capabilities\(session, project, user_id=context\.user_id, visible_project_ids=set\(context\.visible_project_ids\)\)\)/);
  assert.match(backendDocumentsRoute, /def _require_tag_edit_permission/);
  assert.match(backendDocumentsRoute, /PROJECT_EDITOR_ROLES/);
  assert.match(backendDocumentsRoute, /require_project_role\(session, project\.id, context\.user_id, set\(context\.visible_project_ids\), PROJECT_EDITOR_ROLES/);
  assert.doesNotMatch(backendDocumentsRoute, /"TagManagement", PermissionAction\.EDIT/);
  assert.doesNotMatch(backendDocumentsRoute, /"ChunkEditing", PermissionAction\.EDIT/);
  assert.match(extractionPipeline, /generate_knowledge_tags/);
  assert.match(extractionPipeline, /_execute_step\(session, settings, adapter, ocr, project, document, version, pipeline, step_name, artifacts\)/);
  assert.match(extractionPipeline, /pipeline: PipelineRun,\s*step_name: str/);
  assert.match(extractionPipeline, /adapter_source": "live-chat-llm-tagger"/);
  assert.match(extractionPipeline, /_attach_document_tag\(session, project\.id, version\.id/);
  assert.match(extractionPipeline, /_attach_chunk_tag\(session, project\.id, chunk\.id/);
  assert.match(extractionPipeline, /source="llm"/);
  assert.doesNotMatch(extractionPipeline, /internal-rule-tagger/);
  assert.doesNotMatch(knowledgePage, /knowledge-artifact-status/);
  assert.doesNotMatch(css, /\.knowledge-artifact-status/);
  assert.doesNotMatch(knowledgePage, /knowledgeDetailArtifactStatus/);
  assert.doesNotMatch(knowledgePage, /knowledgeDetailMarkdownArtifactSummary/);
  assert.match(knowledgePage, /knowledgeDetailRetryLimitReached/);
  assert.match(knowledgePage, /CanonicalMarkdownSource/);
  assert.match(knowledgePage, /manual_edit_enabled/);
  assert.match(knowledgePage, /KnowledgeDetailCompletionGate/);
  assert.match(knowledgePage, /review-banner/);
  assert.match(knowledgePage, /captureManualSelection/);
  assert.match(knowledgePage, /const canonicalRoot = viewer\.querySelector/);
  assert.match(knowledgePage, /offsetScope: viewMode === "markdown" \? "canonical_markdown" : "source_anchor"/);
  assert.match(knowledgePage, /preRange\.selectNodeContents\(offsetRoot\)/);
  assert.match(knowledgePage, /submitManualChunk/);
  assert.match(knowledgePage, /manual-chunk-popover/);
  assert.match(knowledgePage, /TagEditor/);
  assert.match(knowledgePage, /document_tags/);
  assert.match(knowledgePage, /tagDetails/);
  assert.match(knowledgePage, /visibleTagDetails/);
  assert.match(knowledgePage, /tag\.source !== "rule"/);
  assert.match(knowledgePage, /const documentTags = visibleTagDetails\(liveDetail\?\.document_tags \?\? \[\]\)/);
  // Published assignments may no longer be fabricated from KnowledgeDetail.
  assert.match(knowledgePage, /<VersionGraphPreview/);
  const versionPreview = await readFile(new URL("../src/components/VersionGraphPreview.tsx", import.meta.url), "utf8");
  assert.match(versionPreview, /getDocumentVersionGraph\(apiFetch/);
  assert.match(versionPreview, /graphProjectionNotReady/);
  assert.doesNotMatch(versionPreview, /@\/lib\/fixtures/);
  const versionEvidence = await readFile(new URL("../src/lib/versionGraphEvidence.ts", import.meta.url), "utf8");
  assert.match(versionEvidence, /tagDetails: tags\(node\.id, "CHUNK_HAS_TAG"\)/);
  assert.match(versionEvidence, /documentTags: tags\(versionId, "VERSION_HAS_TAG"\)/);
  assert.doesNotMatch(knowledgePage, /function ChunkTagSummary/);
  assert.match(knowledgePage, /knowledgeDetailChunkTagResults/);
  assert.match(knowledgePage, /function TagResultStrip/);
  assert.match(knowledgePage, /className=\{`tag-result-strip \$\{className\}`\}/);
  assert.match(knowledgePage, /className="tag-result-strip-list"/);
  assert.match(knowledgePage, /className="document-tag-result-strip"/);
  assert.match(knowledgePage, /label=\{t\("knowledgeDetailChunkTagResults"\)\}/);
  assert.doesNotMatch(knowledgePage, /<ChunkTagSummary/);
  assert.match(knowledgePage, /className=\{`knowledge-tag-chip tag-source-\$\{tag\.source\}`\}/);
  assert.match(knowledgePage, /autoTagWholeDocument/);
  assert.match(knowledgePage, /autoTagOneChunk/);
  assert.match(knowledgePage, /documentView === "tags"/);
  assert.match(knowledgePage, /knowledgeDetailTagTab/);
  assert.match(knowledgePage, /knowledge-tag-add-button/);
  assert.match(knowledgePage, /knowledge-tag-inline-input/);
  assert.match(knowledgePage, /event\.key === "Enter"/);
  assert.match(knowledgePage, /event\.key === "Escape"/);
  assert.match(css, /\.knowledge-tag-editor/);
  assert.match(css, /\.knowledge-tag-add-button/);
  assert.match(css, /\.knowledge-tag-inline-input/);
  assert.match(css, /\.document-tag-panel/);
  assert.match(css, /\.manual-chunk-popover/);
  assert.match(css, /\.document-article\s*\{[\s\S]*gap:\s*34px/);
  assert.match(css, /\.document-page\s*\{[\s\S]*box-sizing:\s*border-box/);
  assert.doesNotMatch(css, /\.document-page\s*\{[\s\S]*aspect-ratio:\s*210\s*\/\s*297/);
  assert.match(css, /\.document-page\s*\{[\s\S]*overflow:\s*visible/);
  assert.match(css, /\.document-page-content\s*\{[\s\S]*overflow:\s*visible/);
  assert.match(css, /\.structured-layout-content\s*\{[\s\S]*overflow:\s*visible/);
  assert.match(css, /\.project-feature-modal\.project-graph-modal\s*\{[\s\S]*height:\s*min\(94vh,\s*920px\)/);
  assert.match(css, /\.document-graph-modal\s*\{[\s\S]*height:\s*min\(94vh,\s*920px\)/);
  assert.match(css, /\.project-graph-modal \.feature-summary\s*\{[\s\S]*grid-template-rows:\s*auto minmax\(0, 1fr\)[\s\S]*min-height:\s*0/);
  assert.match(css, /\.document-graph-modal > \.graph-explorer,[\s\S]*\.project-graph-modal \.graph-explorer\s*\{[\s\S]*height:\s*100%[\s\S]*min-height:\s*0/);
  assert.match(css, /\.document-graph-modal \.graph-explorer-left,[\s\S]*\.project-graph-modal \.graph-explorer-left\s*\{[\s\S]*height:\s*100%/);
  assert.match(css, /\.graph-explorer\s*\{[\s\S]*grid-template-columns:\s*minmax\(720px, 1fr\) minmax\(300px, 360px\)[\s\S]*height:\s*100%[\s\S]*overflow:\s*hidden/);
  assert.match(css, /\.graph-explorer-toolbar\s*\{/);
  assert.match(css, /\.graph-explorer-left\s*\{[\s\S]*height:\s*100%/);
  assert.match(css, /\.graph-explorer-canvas\s*\{[\s\S]*flex:\s*1 1 0[\s\S]*cursor:\s*grab/);
  assert.match(css, /\.graph-explorer-edges path\s*\{/);
  assert.match(css, /\.graph-explorer-edges path\.relation-contains/);
  assert.match(css, /\.graph-explorer-edges path\.is-hint-edge/);
  assert.match(css, /\.graph-explorer-scene\[data-zoom-band="structure"\]/);
  assert.match(css, /\.graph-explorer-edge-label\s*\{/);
  assert.match(css, /\.graph-explorer-node\s*\{[\s\S]*cursor:\s*grab/);
  assert.match(css, /\.graph-explorer-node\.is-hint:not\(\.is-selected\)/);
  assert.match(css, /\.graph-explorer-node\.is-hint \.graph-explorer-node-copy\s*\{[\s\S]*display:\s*none/);
  assert.match(css, /\.graph-explorer-node\.node-project\s*\{[\s\S]*border-radius:\s*999px/);
  assert.match(css, /\.graph-explorer-node\.node-document\s*\{[\s\S]*border-left:\s*4px solid var\(--calm-green\)/);
  assert.match(css, /\.graph-explorer-node\.node-chunk\s*\{[\s\S]*border-radius:\s*999px/);
  assert.match(css, /\.graph-explorer-node\.node-tag::after/);
  assert.match(css, /\.graph-explorer-node\.node-tag \.graph-explorer-node-icon/);
  assert.match(css, /\.graph-explorer-node\.node-group\s*\{[\s\S]*width:\s*156px/);
  assert.match(css, /\.graph-explorer-inspector\s*\{[\s\S]*height:\s*100%[\s\S]*overflow:\s*auto/);
  assert.match(css, /\.graph-explorer-chip-list button/);
  assert.match(css, /@media \(max-width:\s*900px\)\s*\{[\s\S]*\.graph-explorer\s*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.doesNotMatch(css, /\.professional-graph-node/);
  assert.doesNotMatch(css, /\.graph-layer-switch/);
  assert.doesNotMatch(css, /\.graph-detail-panel/);
  assert.doesNotMatch(css, /\.graph-canvas-legend/);
  assert.doesNotMatch(css, /\.document-graph-node/);
  assert.doesNotMatch(css, /\.document-graph-canvas/);
  assert.equal(zh.graphExplorerTitle, "知識圖譜");
  assert.equal(en.graphExplorerTitle, "Knowledge Graph");
  assert.equal(zh.graphExplorerZoomControls, "知識圖譜縮放控制");
  assert.equal(en.graphExplorerZoomControls, "Knowledge graph zoom controls");
  assert.equal(zh.graphExplorerInspectorEmptyTitle, "選取節點或關聯");
  assert.equal(en.graphExplorerInspectorEmptyTitle, "Select a node or relationship");
  assert.equal(zh.graphExplorerNodeCount, "節點數");
  assert.equal(en.graphExplorerNodeCount, "Nodes");
  assert.equal(zh.graphExplorerVersion, "版本");
  assert.equal(en.graphExplorerVersion, "Version");
  assert.equal(zh.graphExplorerVersionStatus, "版本狀態");
  assert.equal(en.graphExplorerVersionStatus, "Version status");
  assert.equal(zh.graphExplorerDocumentStatus, "{chunks} 個切片 · {tags} 個標籤");
  assert.equal(en.graphExplorerDocumentStatus, "{chunks} chunks · {tags} tags");
  assert.equal(zh.graphRelationChunked, "切片");
  assert.equal(en.graphRelationChunked, "Chunked");
  assert.equal(zh.graphRelationSourceUpload, "上傳");
  assert.equal(en.graphRelationSourceUpload, "Upload");
  assert.equal(zh.graphRelationSourceFtp, "FTP");
  assert.equal(en.graphRelationSourceFtp, "FTP");
  assert.equal(zh.graphRelationSourceSftp, "SFTP");
  assert.equal(en.graphRelationSourceSftp, "SFTP");
  assert.equal(zh.graphRelationSourceFtps, "FTPS");
  assert.equal(en.graphRelationSourceFtps, "FTPS");
  assert.equal(zh.graphRelationSourceSsh, "SSH");
  assert.equal(en.graphRelationSourceSsh, "SSH");
  assert.equal(zh.graphRelationSourceS3, "S3");
  assert.equal(en.graphRelationSourceS3, "S3");
  assert.equal(zh.graphRelationSourceHttpApi, "HTTP API");
  assert.equal(en.graphRelationSourceHttpApi, "HTTP API");
  assert.equal(zh.graphRelationSourceReferenceProject, "參考專案");
  assert.equal(en.graphRelationSourceReferenceProject, "Referenced project");
  assert.equal(zh.graphLayerStructure, "結構");
  assert.equal(en.graphLayerStructure, "Structure");
  assert.equal(zh.graphDetailPanelTitle, "關係詳情");
  assert.equal(en.graphDetailPanelTitle, "Relationship details");
  assert.equal(zh.graphRelationTaggedAs, "貼標");
  assert.equal(en.graphRelationTaggedAs, "Tagged as");
  assert.match(css, /\.layout-block\s*\{[\s\S]*margin:\s*0/);
  assert.match(css, /\.layout-block\s*\{[\s\S]*overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(css, /\.layout-block\s*\{[^}]*margin-left:\s*-15px/);
  assert.match(css, /\.chunk-title-row\s*\{[\s\S]*justify-content:\s*space-between/);
  assert.match(css, /\.chunk-title-meta\s*\{[\s\S]*align-items:\s*center/);
  assert.match(css, /\.chunk-inline-meta\s*\{[\s\S]*color:\s*var\(--muted\)/);
  assert.match(css, /\.chunk-inline-meta\s*\{[\s\S]*font-size:\s*12px/);
  assert.match(css, /\.chunk-inline-meta span \+ span::before\s*\{[\s\S]*content:\s*"·"/);
  assert.match(css, /\.chunk-technical-id\s*\{[\s\S]*color:\s*var\(--muted\)/);
  assert.match(css, /\.chunk-technical-id\s*\{[\s\S]*font-size:\s*11px/);
  assert.match(css, /\.chunk-technical-id\s*\{[\s\S]*text-align:\s*right/);
  assert.match(css, /@media \(max-width:\s*640px\)\s*\{[\s\S]*\.chunk-technical-id\s*\{[\s\S]*flex-basis:\s*100%/);
  assert.match(css, /\.chunk-content-shell\s*\{[\s\S]*margin:\s*14px 0 0/);
  assert.match(css, /\.chunk-content-shell\s*\{[\s\S]*border-left:\s*3px solid rgba\(95, 174, 136, 0\.22\)/);
  assert.match(css, /\.chunk-content-shell\s*\{[\s\S]*background:\s*#fbfdfc/);
  assert.match(css, /\.extraction-chunks \.chunk-safe-markdown\s*\{[\s\S]*line-height:\s*1\.78/);
  assert.match(css, /\.extraction-chunks \.chunk-card \.safe-markdown p,[\s\S]*margin:\s*0 0 12px/);
  assert.match(css, /\.extraction-chunks \.chunk-card \.safe-markdown p,[\s\S]*line-height:\s*inherit/);
  assert.match(css, /\.extraction-chunks\.chunk-list\.compact \.chunk-card \.safe-markdown p,[\s\S]*margin:\s*0 0 12px/);
  assert.match(css, /\.extraction-chunks \.chunk-card \.safe-markdown li \+ li\s*\{[\s\S]*margin-top:\s*6px/);
  assert.match(css, /\.extraction-chunks \.chunk-media-description\s*\{[\s\S]*line-height:\s*1\.75/);
  assert.doesNotMatch(css, /\.chunk-tag-summary/);
  assert.match(css, /\.tag-result-strip\s*\{[\s\S]*border-top:\s*1px solid var\(--cool-gray\)/);
  assert.match(css, /\.tag-result-strip-list\s*\{[\s\S]*flex-wrap:\s*wrap/);
  assert.match(css, /\.knowledge-tag-editor-label/);
  assert.match(backendDocumentsRoute, /source_model\.source != "rule"/);
  assert.match(backendDocumentsRoute, /delete\(ChunkTag\)\.where\(ChunkTag\.chunk_id == chunk_id, ChunkTag\.source == "rule"\)/);
  assert.match(extractionPipeline, /_delete_rule_tag_links/);
  assert.match(extractionPipeline, /ChunkTag\.source == "rule"/);
  assert.match(backendModels, /source: Mapped\[str\] = mapped_column\(String\(32\), nullable=False, default="llm"\)/);
  assert.match(llmTagDefaultMigration, /ALTER COLUMN source SET DEFAULT 'llm'/);
  assert.match(zh.knowledgeDetailMarkdownUnavailable, /Markdown artifact/);
  assert.match(en.knowledgeDetailMarkdownUnavailable, /Markdown artifact is unavailable/);
  assert.equal(zh.knowledgeDetailSelectChunkAria, "選取第 {number} 個切片，識別碼 {id}");
  assert.equal(en.knowledgeDetailSelectChunkAria, "Select chunk {number}, identifier {id}");
  assert.equal(zh.knowledgeDetailChunkTagResults, "貼標結果");
  assert.equal(en.knowledgeDetailChunkTagResults, "Tag results");
  assert.equal(zh.knowledgeDetailStepAutoTag, "AI自動貼標");
  assert.equal(en.knowledgeDetailStepAutoTag, "AI auto tagging");
  assert.equal(zh.knowledgeDetailManualEditDisabled, "手動編輯已停用");
  assert.equal(en.knowledgeDetailManualEditDisabled, "Manual edit disabled");
  assert.equal(zh.knowledgeDetailManualChunking, "手動切片");
  assert.equal(zh.knowledgeDetailManualEditPermissionDenied, "目前帳號沒有手動切片權限。");
  assert.equal(zh.knowledgeDetailManualEditPipelineRunning, "Pipeline 執行中，暫時無法手動切片。");
  assert.equal(zh.knowledgeDetailManualChunkFailed, "手動切片失敗，請重新整理後再試。");
  assert.doesNotMatch(JSON.stringify(zh), new RegExp("\\u5207\\u584a"));
  assert.equal(zh.knowledgeDetailDocumentTags, "文件標籤");
  assert.equal(en.knowledgeDetailDocumentTags, "Document tags");
  assert.equal(zh.knowledgeDetailTagTab, "貼標");
  assert.equal(en.knowledgeDetailTagTab, "Tags");
  assert.match(approvalDetail, /approvalNoLiveValidationEvidence/);
  assert.equal(zh.approvalNoLiveValidationEvidence, "尚無 live 批次驗證證據");
  assert.equal(en.approvalNoLiveValidationEvidence, "No live batch validation evidence yet");
  assert.match(evidenceViewer, /approvalEvidenceNoLiveOriginal/);
  assert.match(zh.approvalEvidenceNoLiveOriginal, /尚無 live 原文 evidence/);
  assert.match(en.approvalEvidenceNoLiveOriginal, /No live original evidence/);
});

test("PIPE-012 gates upload extraction and Knowledge Detail until submission_ready", async () => {
  const [importPage, knowledgePage, sourceModals, css, zh, en] = await Promise.all([
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/KnowledgeSourceModals.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);

  assert.match(importPage, /pipelineReachedExtractionGate/);
  assert.match(importPage, /pipelineFailedBeforeExtractionGate/);
  assert.match(importPage, /pollPipelineUntilCompletionGate/);
  assert.match(importPage, /options\.startExtraction && results\.length === 1/);
  assert.match(importPage, /onRetryPipeline=\{retryUploadModalPipeline\}/);
  assert.match(sourceModals, /uploadExtractionReady/);
  assert.match(sourceModals, /failedAutoExtraction/);
  assert.match(sourceModals, /pendingAutoExtraction/);
  assert.match(sourceModals, /autoExtract && uploadExtractionReady\(documents\[0\]\)/);
  assert.match(sourceModals, /onRetryPipeline\(liveProgressDocument/);
  assert.match(sourceModals, /knowledgeDetailPipelineFailedTitle/);
  assert.match(sourceModals, /uploadCloseToProject/);
  assert.doesNotMatch(sourceModals, /if \(autoExtract\) onClose\(\);/);
  assert.match(knowledgePage, /completionGateBlocksKnowledgeDetail/);
  assert.match(knowledgePage, /shouldPollKnowledgeCompletionGate/);
  assert.match(knowledgePage, /KnowledgeDetailCompletionGate/);
  assert.match(knowledgePage, /knowledgeGateBlocked/);
  assert.match(knowledgePage, /liveDetail && !knowledgeGateBlocked/);
  assert.match(knowledgePage, /knowledge-detail-gate/);
  assert.match(css, /\.knowledge-detail-gate\s*\{/);
  assert.match(css, /\.upload-progress-error-message\s*\{/);
  assert.equal(zh.knowledgeDetailCompletionGateTitle, "正在完成知識萃取");
  assert.equal(en.knowledgeDetailCompletionGateTitle, "Completing knowledge extraction");
  assert.equal(zh.uploadCloseToProject, "返回專案文件");
  assert.equal(en.uploadCloseToProject, "Back to project documents");
});

test("danger action buttons expose visible hover and focus states", async () => {
  const css = await readFile(new URL("../src/app/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.action-button\.danger:hover\s*\{/);
  assert.match(css, /\.action-button\.danger:hover[\s\S]*background:\s*#cf6864/);
  assert.match(css, /\.action-button\.danger:hover[\s\S]*box-shadow:/);
  assert.match(css, /\.action-button\.danger:focus-visible\s*\{/);
});

test("Milestone 15B reports and system management do not use protected fixture fallback data", async () => {
  const [reports, system] = await Promise.all([
    readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8")
  ]);

  for (const forbidden of [
    "projectRanking",
    "projectReferenceRanking",
    "documentReferenceRanking",
    "ownerProjects",
    "pipelineMetrics",
    "alertRows",
    "csvRowsByTopic",
    "法規知識庫",
    "財務內控中心",
    "產品支援手冊",
    "個資保護作業準則"
  ]) assert.doesNotMatch(reports, new RegExp(forbidden));

  assert.match(reports, /ReportEmptyState/);
  assert.match(reports, /downloadReportCsv\(apiFetch/);
  assert.doesNotMatch(reports, /ReportChart/);

  for (const forbidden of [
    "fixtureUsers",
    "fixtureRoles",
    "fixtureGroupMappings",
    "fixtureModels",
    "fixtureSystemStatus",
    "initialPermissions",
    "not_checked_fixture",
    "Peter Wang",
    "Linda Chen",
    "PaddleOCR",
    "risk-ai.openai.azure.com"
  ]) assert.doesNotMatch(system, new RegExp(forbidden.replace(/[.]/g, "\\.")));

  assert.match(system, /useState<UserRow\[\]>\(\[\]\)/);
  assert.match(system, /useState<RoleRow\[\]>\(\[\]\)/);
  assert.match(system, /useState<ModelRow\[\]>\(\[\]\)/);
  assert.match(system, /useState<OperationsStatusResponse \| null>\(null\)/);
  assert.match(system, /getSystemStatus\(apiFetch\)\.catch\(\(\) => null\)/);
  assert.match(system, /EmptyInlineState/);
  assert.match(system, /systemStatus \? <>/);
});

test("Milestone 7.1 API client exposes serving completion helpers", async () => {
  const [source, importPage, uploadModals, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/import/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/KnowledgeSourceModals.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of [
    "SwitchActiveVersionPayload",
    "switchActiveDocumentVersion",
    "UploadConfigResponse",
    "getUploadConfig",
    "getDocumentLifecycleImpact",
    "updateDocumentLifecycle",
    "getProjectGraph",
    "getProjectGraphNeighbors",
    "getProjectGraphPaths",
    "getDocumentVersionGraph",
    "getProjectServingStatus",
    "ProjectServingStatusResponse",
    "DocumentReferenceResponse",
    "DocumentReferenceEventResponse",
    "listProjectDocumentReferences",
    "createProjectDocumentReference",
    "detachDocumentReference",
    "requestDocumentReferenceSync",
    "listDocumentReferenceEvents",
    "getImpactedReferenceProjects",
    "resolveDocumentReferenceEvent",
    "queryProjectChat",
    "listNotifications",
    "markNotificationRead",
    "ProjectGraphResponse",
    "ProjectChatQueryResponse",
    "NotificationResponse"
  ]) assert.match(source, new RegExp(required));
  assert.doesNotMatch(source, /getKnowledgeGraph/);
  assert.doesNotMatch(source, /`\/knowledge-graph/);
  assert.match(source, /\/switch-active/);
  assert.match(source, /\/system\/upload-config/);
  assert.match(source, /\/lifecycle-impact\?status=/);
  assert.match(source, /node_limit=/);
  assert.match(source, /\/serving-status/);
  assert.match(source, /\/document-references/);
  assert.match(source, /\/document-reference-events\/impacted-projects/);
  assert.match(source, /\/chat\/query/);
  assert.match(importPage, /getDocumentLifecycleImpact\(apiFetch/);
  assert.match(importPage, /updateDocumentLifecycle\(apiFetch/);
  assert.match(importPage, /getUploadConfig\(apiFetch\)\.catch\(\(\) => null\)/);
  assert.match(importPage, /switchActiveDocumentVersion\(apiFetch, target\.version\.id/);
  assert.match(importPage, /lock_version: target\.version\.lockVersion/);
  assert.match(importPage, /audit_reason: reason/);
  assert.match(importPage, /maxUploadBytes=\{maxUploadSizeMb \* 1024 \* 1024\}/);
  assert.match(uploadModals, /maxUploadBytes = DEFAULT_MAX_UPLOAD_BYTES/);
  assert.match(uploadModals, /validateUploadFile\(file, maxUploadBytes\)/);
  assert.match(uploadModals, /format\("uploadMaxSizeDynamic", \{ size: maxUploadMb \}\)/);
  assert.match(uploadModals, /format\("uploadReasonTooLargeDynamic", \{ size: maxUploadMb \}\)/);
  assert.match(importPage, /status: requestedStatus, impact_confirmed: false/);
  assert.match(importPage, /const \[lifecycleNotice, setLifecycleNotice\] = useState<LifecycleNotice \| null>\(null\)/);
  assert.match(importPage, /currentStatus === "inactive" && requestedStatus === "active"/);
  assert.match(importPage, /setLifecycleNotice\(\{[\s\S]*projectImportReactivatedTitle[\s\S]*projectImportReactivatedMessage[\s\S]*\}\)/);
  assert.match(importPage, /className="lifecycle-notice-popup"/);
  assert.match(importPage, /setLiveDocuments\(\(current\) => current\.map\(\(item\) => item\.id === document\.id \? liveDocumentFromSummary\(updated, t\) : item\)\)/);
  assert.match(importPage, /lockVersion: document\.lock_version/);
  assert.match(importPage, /change\.to === "deleted" \|\| updated\.status === "deleted"/);
  assert.match(importPage, /setLiveDocuments\(\(current\) => current\.filter\(\(item\) => item\.id !== change\.documentId\)\)/);
  assert.match(importPage, /setCreatedImports\(\(current\) => current\.filter\(\(item\) => item\.id !== change\.documentId\)\)/);
  assert.equal(zh.projectImportReactivatedTitle, "文件已重新啟用");
  assert.equal(en.projectImportReactivatedTitle, "Document re-enabled");
  assert.equal(zh.uploadMaxSizeDynamic, "單檔最多 {size} MB");
  assert.equal(en.uploadMaxSizeDynamic, "{size} MB max per file");
  assert.equal(typeof zh.projectImportSwitchActiveVersion, "string");
  assert.equal(typeof en.projectImportSwitchActiveVersion, "string");
  assert.equal(typeof zh.projectImportDismissLifecycleNotice, "string");
  assert.equal(typeof en.projectImportDismissLifecycleNotice, "string");
  assert.doesNotMatch(importPage, /fall back to optimistic local state/);
});

test("Milestone 8A Project Chat uses live retrieval citations without fixture fallback", async () => {
  const [api, chat, evidence, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ChatResponseEvidence.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of ["excerpt", "content_type", "page", "source_mapping", "index_name", "selected_version_ids", "status", "retrieval_strategy"]) assert.match(api, new RegExp(required));
  for (const required of ["readiness", "active_document_count", "ready_index_count", "graph_ready_count", "publication_generation", "chunk_count", "graph_sync_status"]) assert.match(api, new RegExp(required));
  assert.match(chat, /retrievalErrorMessage/);
  assert.match(chat, /getProjectServingStatus\(apiFetch, projectId\)/);
  assert.match(chat, /project-serving-status/);
  assert.match(chat, /projectChatServingStatus/);
  assert.match(chat, /const servingReadyIds = useMemo/);
  assert.match(chat, /chunks: servingDocument\?\.chunk_count \?\? 0/);
  assert.match(chat, /document\.documentStatus === "active" && document\.versionStatus === "active" && servingReadyIds\.has\(document\.id\)/);
  assert.match(chat, /const eligibleIds = useMemo/);
  assert.match(chat, /const allIds = eligibleIds/);
  assert.match(chat, /if \(!eligibleIds\.includes\(id\)\) return/);
  assert.match(chat, /aria-disabled=\{!eligible\}/);
  assert.match(chat, /disabled=\{!eligible\}/);
  assert.match(chat, /projectChatDocumentInactive/);
  assert.match(chat, /projectChatDocumentUnavailableHelp/);
  assert.match(chat, /allScopeIdsEligible/);
  assert.match(chat, /entry\.status === "no_answer"/);
  assert.match(chat, /<ChatResponseEvidence/);
  assert.match(evidence, /setSelected\(\{ citation, ordinal \}\)/);
  assert.match(evidence, /selected\.citation\.excerpt/);
  assert.doesNotMatch(chat, /fixture 引用已停用/);
  assert.doesNotMatch(chat, /信用風險模型治理規範\.pdf · v4 · C-001 · 第 3 頁/);
  assert.equal(zh.projectChatServingReady, "Serving ready");
  assert.equal(en.projectChatServingReady, "Serving ready");
  assert.equal(zh.projectChatDocumentInactive, "停用");
  assert.equal(en.projectChatDocumentInactive, "Disabled");
});

test("Milestone 15C dashboard chat graph and shared formal components use live-only data without fallback fixtures", async () => {
  const [home, chat, graph, pipelineList, documentGraph, zh, en] = await Promise.all([
    readFile(new URL("../src/app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectGraphPreview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/PipelineList.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/DocumentGraphPreview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8")
  ]);

  assert.doesNotMatch(home, /@\/lib\/fixtures/);
  for (const required of ["listProjects(apiFetch)", "getApprovalSummary(apiFetch)", "listPendingApprovals(apiFetch)", "getReportSummary(apiFetch"]) assert.match(home, new RegExp(required.replace(/[()]/g, "\\$&")));
  for (const forbidden of ["value=\"12\"", "value=\"31\"", "value=\"9\"", "value=\"96%\"", "knowledge-ops", "risk-model-review"]) assert.doesNotMatch(home, new RegExp(forbidden.replace(/[.]/g, "\\.")));

  for (const forbidden of [
    "fallbackDocuments",
    "documentSource, setDocumentSource] = useState<\"loading\" | \"live\" | \"fallback\"",
    "fixture 引用",
    "信用風險模型治理規範.pdf",
    "重大模型異動需先完成直屬主管",
    "重大模型異動需完成主管"
  ]) assert.doesNotMatch(chat, new RegExp(forbidden.replace(/[()|]/g, "\\$&")));
  assert.match(chat, /setUploadError\(t\("projectChatBatchLiveScopeRequired"\)\)/);
  assert.match(chat, /t\("projectChatNoBackendAnswer"\)/);

  for (const forbidden of ["fallbackNodeTemplates", "fallbackEdges", "\"fallback\"", "graphProjectFallbackStatus", "graphProjectFallbackProjectName"]) assert.doesNotMatch(graph, new RegExp(forbidden));
  assert.match(graph, /getProjectGraph\(apiFetch, projectId, 120\)/);
  assert.match(graph, /graphProjectTruncatedStatus/);
  assert.match(graph, /liveGraph\?\.truncated/);
  assert.match(graph, /graphProjectUnavailableStatus/);
  assert.doesNotMatch(pipelineList, /@\/lib\/fixtures/);
  assert.doesNotMatch(pipelineList, /pipelineRuns/);
  assert.match(pipelineList, /runs = \[\]/);
  assert.doesNotMatch(documentGraph, /@\/lib\/fixtures/);
  assert.doesNotMatch(documentGraph, /chunks\.map/);
  assert.match(documentGraph, /GraphExplorer/);
  assert.match(documentGraph, /graphChunks = \[\]/);
  assert.match(documentGraph, /documentTags = \[\]/);
  assert.match(documentGraph, /tagMap/);
  assert.match(documentGraph, /chunkTags\(chunk\)/);
  assert.doesNotMatch(documentGraph, /node\.detail/);
  assert.doesNotMatch(zh, /graphProjectFallback/);
  assert.doesNotMatch(en, /graphProjectFallback/);
});

test("Milestone 8B Project Chat exposes persistence feedback and validation APIs", async () => {
  const [api, chat, zh, en] = await Promise.all([
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  for (const required of [
    "ProjectChatRecordResponse",
    "ProjectChatConversationResponse",
    "ProjectChatConversationDeleteResponse",
    "ValidationRunResponse",
    "listProjectChatConversations",
    "getProjectChatConversation",
    "deleteProjectChatConversation",
    "updateProjectChatFeedback",
    "createProjectChatValidationRun",
    "getProjectChatValidationRun",
    "retryFailedProjectChatValidationItems",
    "/chat/conversations",
    "method: \"DELETE\"",
    "/feedback",
    "/chat/validation-runs",
    "/retry-failed"
  ]) assert.match(api, new RegExp(required.replace(/[()]/g, "\\$&")));
  assert.match(chat, /listProjectChatConversations\(apiFetch, projectId\)/);
  assert.match(chat, /deleteProjectChatConversation\(apiFetch, params\.id, target\.id\)/);
  assert.match(chat, /persisted: true/);
  assert.match(chat, /target\.persisted/);
  assert.doesNotMatch(chat, /target\.entries\.length\)/);
  assert.match(chat, /project-history-delete/);
  assert.match(chat, /projectChatDeleteConversationTitle/);
  assert.match(chat, /projectChatConfirmDeleteConversation/);
  assert.match(chat, /setDeleteTargetId\(conversation\.id\)/);
  assert.match(chat, /setConversations\(remaining\)/);
  assert.doesNotMatch(chat, /blankConversation/);
  assert.match(chat, /conversation_id: activeConversation\?\.persisted && isUuid\(localConversationId\) \? localConversationId : undefined/);
  assert.match(chat, /recordId: result\.chat_record_id/);
  assert.match(chat, /updateProjectChatFeedback\(apiFetch/);
  assert.match(chat, /createProjectChatValidationRun\(apiFetch/);
  assert.match(chat, /getProjectChatValidationRun\(apiFetch/);
  assert.match(chat, /retryFailedProjectChatValidationItems\(apiFetch/);
  assert.match(chat, /window\.setInterval/);
  assert.match(chat, /format\("documentChatValidationRun"/);
  assert.equal(en.documentChatValidationRun, "Validation Run: {id}");
  assert.match(chat, /projectChatRetryFailedQuestions/);
  assert.equal(zh.projectChatRetryFailedQuestions, "重跑失敗題");
  assert.equal(en.projectChatRetryFailedQuestions, "Rerun failed questions");
  assert.equal(zh.projectChatConfirmDeleteConversation, "刪除對話");
  assert.equal(en.projectChatConfirmDeleteConversation, "Delete conversation");
  assert.match(zh.projectChatDeleteConversationHelp, /稽核/);
  assert.match(en.projectChatDeleteConversationHelp, /audit/);
});

test("CHG-190 Project Chat restores persisted history without implicit blank conversations", async () => {
  const [chat, zh, en] = await Promise.all([
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  assert.match(chat, /useState<ProjectConversation\[]>\(\[]\)/);
  assert.match(chat, /useState<string \| null>\(null\)/);
  assert.doesNotMatch(chat, /useState<ProjectConversation\[]>\(\(\) =>/);
  assert.doesNotMatch(chat, /blankConversation/);
  assert.match(chat, /setHistoryStatus\("loading"\)/);
  assert.match(chat, /setHistoryStatus\("ready"\)/);
  assert.match(chat, /setHistoryStatus\("error"\)/);
  assert.match(chat, /setConversations\(\[]\)/);
  assert.match(chat, /setActiveConversationId\(null\)/);
  assert.match(chat, /const unavailableVersionLabel = t\("projectChatUnavailableVersion"\)/);
  assert.match(chat, /operationalErrorMessage\(error, t, format, "projectChatHistoryLoadFailed"\)/);
  assert.match(chat, /listProjectChatConversations\(apiFetch, projectId\)\.then/);
  assert.match(chat, /}, \[apiFetch, authReady, params\?\.id, unavailableVersionLabel\]\);/);
  assert.match(chat, /}, \[apiFetch, authReady, format, params\?\.id, t\]\);/);
  const documentLoadEffect = chat.slice(chat.indexOf("Promise.all([listProjectDocuments"), chat.indexOf("}, [apiFetch, authReady, params?.id, unavailableVersionLabel]);"));
  assert.doesNotMatch(documentLoadEffect, /listProjectChatConversations/);
  assert.doesNotMatch(documentLoadEffect, /setHistoryStatus/);
  assert.doesNotMatch(documentLoadEffect, /setConversations\(\[]\)/);
  assert.match(chat, /const restored = history\.map\(conversationFromHistory\)/);
  assert.match(chat, /setActiveConversationId\(restored\[0\]\.id\)/);
  assert.match(chat, /persistedConversationCount/);
  assert.match(chat, /projectChatHistoryEmptyTitle/);
  assert.match(chat, /projectChatHistoryLoadFailed/);
  assert.match(chat, /projectChatDraftBadge/);
  assert.match(chat, /existingDraft/);
  assert.match(chat, /activeConversation\?\.id \?\? newConversationId\(\)/);
  assert.match(chat, /setActiveConversationId\(localConversationId\)/);
  assert.equal(zh.projectChatHistoryLoadFailed, "無法載入對話紀錄");
  assert.equal(en.projectChatHistoryLoadFailed, "Unable to load conversation history");
  assert.equal(zh.projectChatHistoryEmptyTitle, "尚無專案對話紀錄");
  assert.equal(en.projectChatHistoryEmptyTitle, "No project conversations yet");
  assert.equal(zh.projectChatDraftBadge, "草稿");
  assert.equal(en.projectChatDraftBadge, "Draft");
});

test("CHG-192 Project Chat conversation box matches document-level Chat Test structure", async () => {
  const [chat, documentChat, evidence, css, spec, trace, plan, testPlan] = await Promise.all([
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/chat-test/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ChatResponseEvidence.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../../SPECIFICATION.md", import.meta.url), "utf8"),
    readFile(new URL("../../TRACEABILITY.md", import.meta.url), "utf8"),
    readFile(new URL("../../DEVELOPMENT_PLAN.md", import.meta.url), "utf8"),
    readFile(new URL("../../TEST_PLAN.md", import.meta.url), "utf8")
  ]);
  assert.match(spec, /CHAT-UX-004/);
  assert.match(trace, /CHAT-UX-004/);
  assert.match(testPlan, /CHAT-UX-004/);
  assert.match(plan, /Project\/Document Chat Conversation Box Parity/);
  assert.match(plan, /Approved by Peter/);

  for (const shared of [
    "chat-conversation-panel",
    "chat-conversation-header",
    "chat-conversation-header-actions",
    "chat-thread",
    "chat-response-pair",
    "chat-message user-message",
    "user-message-body",
    "chat-message assistant-message",
    "assistant-message-body",
    "answer-judgment",
    "chat-composer"
  ]) {
    assert.match(documentChat, new RegExp(shared.replace(/[()]/g, "\\$&")));
    assert.match(chat, new RegExp(shared.replace(/[()]/g, "\\$&")));
  }

  assert.match(chat, /<div className="chat-conversation-panel project-chat-main">/);
  assert.match(chat, /className="chat-thread" aria-live="polite" ref=\{chatThreadRef\}/);
  assert.match(chat, /className="chat-response-pair"/);
  assert.match(chat, /<UserRound size=\{17\} \/>/);
  assert.match(chat, /<ChatResponseEvidence/);
  assert.match(documentChat, /<ChatResponseEvidence/);
  assert.match(evidence, /className=\{citationsContainerClassName\}/);
  assert.match(evidence, /<strong>\{citationsLabel\}<\/strong>/);
  assert.doesNotMatch(chat, /project-chat-thread/);
  assert.doesNotMatch(chat, /project-chat-entry/);
  assert.doesNotMatch(chat, /project-user-question/);
  assert.doesNotMatch(chat, /project-assistant-answer/);
  assert.doesNotMatch(chat, /project-citations/);

  const sidebarIndex = chat.indexOf('<aside className="project-chat-sidebar">');
  const servingIndex = chat.indexOf("project-serving-status");
  const dividerIndex = chat.indexOf("project-sidebar-divider");
  const mainIndex = chat.indexOf('<div className="chat-conversation-panel project-chat-main">');
  const threadIndex = chat.indexOf('className="chat-thread"');
  assert.ok(sidebarIndex >= 0 && servingIndex > sidebarIndex, "serving status should live in the sidebar");
  assert.ok(servingIndex < dividerIndex, "serving status should sit with the reference/scope area before history divider");
  assert.ok(servingIndex < mainIndex, "serving status should not be inside the right conversation panel");
  assert.ok(threadIndex > mainIndex, "message thread should remain inside the right conversation panel");

  assert.match(css, /\.project-chat-sidebar\s*\{[\s\S]*grid-template-rows:\s*minmax\(0, 3fr\) auto auto minmax\(0, 2fr\) auto/);
  assert.match(css, /\.project-chat-main\s*\{[\s\S]*grid-template-rows:\s*auto minmax\(0, 1fr\) auto/);
  assert.doesNotMatch(css, /\.project-chat-thread/);
  assert.doesNotMatch(css, /\.project-assistant-answer/);
  assert.doesNotMatch(css, /\.project-citations/);

  const headerActions = chat.slice(chat.indexOf('className="chat-conversation-header-actions"'), chat.indexOf("</header>", mainIndex));
  const actionOrder = headerActions.indexOf('t("uploadTestConversations")') < headerActions.indexOf('t("downloadConversation")')
    && headerActions.indexOf('t("downloadConversation")') < headerActions.indexOf('t("newConversation")');
  assert.equal(actionOrder, true);
  assert.match(chat, /project-history-delete/);
  assert.match(chat, /projectChatNewConversationWithScope/);
});

test("CHG-193 Project Chat serving readiness summary is collapsible by default", async () => {
  const [chat, css, spec, trace, plan, testPlan] = await Promise.all([
    readFile(new URL("../src/components/ProjectChatTest.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../../SPECIFICATION.md", import.meta.url), "utf8"),
    readFile(new URL("../../TRACEABILITY.md", import.meta.url), "utf8"),
    readFile(new URL("../../DEVELOPMENT_PLAN.md", import.meta.url), "utf8"),
    readFile(new URL("../../TEST_PLAN.md", import.meta.url), "utf8")
  ]);
  assert.match(spec, /CHAT-UX-005/);
  assert.match(trace, /CHAT-UX-005/);
  assert.match(testPlan, /CHAT-UX-005/);
  assert.match(plan, /Project Chat Collapsible Serving Readiness Summary/);
  assert.match(plan, /Approved by Peter/);

  assert.match(chat, /const \[servingExpanded, setServingExpanded\] = useState\(false\)/);
  assert.match(chat, /aria-expanded=\{servingExpanded\}/);
  assert.match(chat, /className="project-serving-toggle"/);
  assert.match(chat, /setServingExpanded\(\(current\) => !current\)/);
  assert.match(chat, /servingExpanded \? <ChevronDown size=\{15\} \/> : <ChevronRight size=\{15\} \/>/);
  assert.match(chat, /servingExpanded \? \(/);
  assert.match(chat, /className="project-serving-documents"/);
  assert.match(chat, /projectChatServingSummary/);
  assert.match(chat, /active_document_count/);
  assert.match(chat, /ready_index_count/);
  assert.match(chat, /graph_ready_count/);

  const sidebarIndex = chat.indexOf('<aside className="project-chat-sidebar">');
  const servingIndex = chat.indexOf("project-serving-status");
  const detailIndex = chat.indexOf('className="project-serving-documents"');
  const dividerIndex = chat.indexOf("project-sidebar-divider");
  const mainIndex = chat.indexOf('<div className="chat-conversation-panel project-chat-main">');
  assert.ok(sidebarIndex >= 0 && servingIndex > sidebarIndex, "serving summary should stay in the sidebar");
  assert.ok(detailIndex > servingIndex, "serving details should remain inside the collapsible status section");
  assert.ok(detailIndex < dividerIndex, "serving details should stay before the history divider");
  assert.ok(servingIndex < mainIndex, "serving summary should not move into the right conversation panel");

  assert.match(css, /\.project-serving-toggle\s*\{/);
  assert.match(css, /\.project-serving-toggle:hover/);
  assert.match(css, /\.project-serving-toggle:focus-visible/);
  assert.match(css, /\.project-serving-documents\s*\{[\s\S]*max-height:\s*74px/);
  assert.match(css, /\.project-serving-documents\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(chat, /toggleDocument\(document\.id\)/);
  assert.match(chat, /listProjectChatConversations\(apiFetch, projectId\)/);
  assert.match(chat, /queryProjectChat\(apiFetch, params\.id!/);
  assert.match(chat, /createProjectChatValidationRun\(apiFetch/);
});
