import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("API documentation is a default logged-in menu item, not a permission-gated feature", async () => {
  const appShell = await readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8");
  assert.match(appShell, /href: "\/api-docs"/);
  assert.match(appShell, /label: t\("apiDocs"\)/);
  assert.match(appShell, /BookOpenText/);
  assert.match(appShell, /href: "\/api-docs"[\s\S]*visible: true/);
  assert.doesNotMatch(appShell, /can\("Menu", "ApiDocumentation", "view"\)/);
  assert.doesNotMatch(appShell, /ApiDocumentation/);
});

test("API documentation appears to the right of system management in the main menu", async () => {
  const appShell = await readFile(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8");
  const approvalIndex = appShell.indexOf('href: "/approve"');
  const reportsIndex = appShell.indexOf('href: "/reports"');
  const systemIndex = appShell.indexOf('href: "/system"');
  const apiDocsIndex = appShell.indexOf('href: "/api-docs"');
  assert.notEqual(approvalIndex, -1);
  assert.notEqual(reportsIndex, -1);
  assert.notEqual(systemIndex, -1);
  assert.notEqual(apiDocsIndex, -1);
  assert.ok(approvalIndex < reportsIndex);
  assert.ok(reportsIndex < systemIndex);
  assert.ok(systemIndex < apiDocsIndex);
});

test("API documentation page covers public API integration without management actions or real secrets", async () => {
  const page = await readFile(new URL("../src/app/api-docs/page.tsx", import.meta.url), "utf8");
  for (const required of [
    "apiDocsOverviewTitle",
    "apiDocsApplicationTitle",
    "apiDocsFlowTitle",
    "POST /api/public/v1/projects/<project_id>/chat",
    "POST /api/public/v1/projects/<project_id>/chat/stream",
    "POST /api/public/v1/chat/responses/<response_id>/feedback",
    "Authorization: Bearer <api_key>",
    "X-NomoSmart-API-Key: <api_key>",
    "employee_id",
    "document_ids",
    "citations",
    "request_id",
    "apiDocsSafetyPublishedOnly"
  ]) assert.match(page, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  for (const forbidden of [
    /createIntegrationClient/,
    /rotateIntegrationClientKey/,
    /revokeIntegrationClient/,
    /replaceIntegrationClientProjectScopes/,
    /nms_[A-Za-z0-9]{8,}/,
    /sk-[A-Za-z0-9]{8,}/,
    /BEGIN (RSA|OPENSSH|PRIVATE) KEY/
  ]) assert.doesNotMatch(page, forbidden);
});

test("API documentation is structured as a professional integration guide before endpoint reference", async () => {
  const page = await readFile(new URL("../src/app/api-docs/page.tsx", import.meta.url), "utf8");
  const overviewIndex = page.indexOf('id: "overview"');
  const applicationIndex = page.indexOf('id: "application"');
  const flowIndex = page.indexOf('id: "flow"');
  const authIndex = page.indexOf('id: "auth"');
  const jsonIndex = page.indexOf('id: "json"');
  assert.notEqual(overviewIndex, -1);
  assert.notEqual(applicationIndex, -1);
  assert.notEqual(flowIndex, -1);
  assert.notEqual(authIndex, -1);
  assert.notEqual(jsonIndex, -1);
  assert.ok(overviewIndex < applicationIndex);
  assert.ok(applicationIndex < flowIndex);
  assert.ok(flowIndex < authIndex);
  assert.ok(authIndex < jsonIndex);
  for (const required of [
    "apiDocsAudienceLabel",
    "apiDocsApplicationSystemName",
    "apiDocsApplicationPurpose",
    "apiDocsApplicationOwner",
    "apiDocsApplicationScope",
    "apiDocsApplicationRate",
    "apiDocsApplicationLifecycle",
    "apiDocsFlowRequestKey",
    "apiDocsFlowPersist"
  ]) assert.match(page, new RegExp(required));
});

test("API documentation navigation synchronizes an equal-height desktop reading pane", async () => {
  const [page, css] = await Promise.all([
    readFile(new URL("../src/app/api-docs/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8")
  ]);
  for (const required of [
    "sectionPaneRef",
    "sectionRefs",
    "activeSection",
    "scrollToSection",
    "syncActiveSection",
    "scheduleActiveSync",
    "largestVisibleArea",
    "programmaticSectionRef",
    "clearProgrammaticScroll",
    "sectionIdFromHash",
    "window.history.pushState",
    "hashchange",
    "popstate",
    "touchstart",
    "prefers-reduced-motion: reduce",
    "aria-current",
    "api-docs-section-card"
  ]) assert.match(page, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(page, /className="api-docs-sections" onScroll=\{scheduleActiveSync\} ref=\{sectionPaneRef\}/);
  assert.match(page, /id=\{section\.id\}[\s\S]*<Panel title=\{t\(section\.title\)\}>/);
  assert.match(page, /aria-current=\{activeSection === section\.id \? "location" : undefined\}/);
  assert.match(page, /sectionPaneRef\.current\.scrollTo\(\{ top: target\.offsetTop, behavior \}\)/);
  assert.match(page, /target\.scrollIntoView\(\{ behavior, block: "start" \}\)/);
  assert.match(css, /\.api-docs-layout\s*\{[^}]*align-items:\s*stretch;[^}]*height:\s*clamp\(520px, calc\(100dvh - 150px\), 760px\);/s);
  assert.match(css, /\.api-docs-sections\s*\{[^}]*height:\s*100%;[^}]*overflow-y:\s*auto;[^}]*scrollbar-gutter:\s*stable;/s);
  assert.match(css, /\.api-docs-nav a\[aria-current="location"\]/);
  assert.match(css, /@media \(max-width: 1100px\)[\s\S]*\.api-docs-layout \{ grid-template-columns: 1fr; height: auto;[\s\S]*\.api-docs-sections \{ height: auto;[^}]*overflow: visible;/s);
});

test("permission matrix does not expose an API documentation toggle", async () => {
  const system = await readFile(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
  assert.match(system, /functionName: "KnowledgeProjects"/);
  assert.match(system, /functionName: "Reports"/);
  assert.match(system, /functionName: "SystemManagement"/);
  assert.doesNotMatch(system, /ApiDocumentation/);
  assert.doesNotMatch(system, /apiDocs/);
});

test("API documentation locale keys stay aligned", async () => {
  const [zh, en] = await Promise.all([
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
  const keys = Object.keys(zh).filter((key) => key.startsWith("apiDocs"));
  assert.ok(keys.length >= 40);
  for (const key of keys) {
    assert.equal(typeof zh[key], "string", key);
    assert.equal(typeof en[key], "string", key);
    assert.notEqual(zh[key].trim(), "", key);
    assert.notEqual(en[key].trim(), "", key);
  }
  assert.equal(zh.apiDocs, "API說明");
  assert.equal(en.apiDocs, "API Documentation");
  assert.match(zh.apiDocsAdminNote, /NomoSmart 系統管理者/);
  assert.match(zh.apiDocsAdminNote, /外部系統名稱/);
  assert.match(zh.apiDocsApplicationRate, /請求/);
  assert.match(en.apiDocsAdminNote, /NomoSmart system administrator/);
  assert.match(en.apiDocsAdminNote, /external system name/);
  assert.match(en.apiDocsApplicationRate, /request/);
});
