import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const home = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
const appShell = readFileSync(new URL("../src/components/AppShell.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const systemWorkspace = readFileSync(new URL("../src/components/SystemManagementWorkspace.tsx", import.meta.url), "utf8");
const zh = JSON.parse(readFileSync(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"));
const en = JSON.parse(readFileSync(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8"));

test("HOME-001 removes the static infrastructure strip and dead presentation", () => {
  assert.doesNotMatch(home, /DataSourceStrip/);
  assert.doesNotMatch(appShell, /DataSourceStrip|sourcePostgres|sourceNeo4j|sourceOpenSearch|source-strip/);
  assert.doesNotMatch(css, /\.source-strip/);

  for (const locale of [zh, en]) {
    assert.equal(locale.sourcePostgres, undefined);
    assert.equal(locale.sourceNeo4j, undefined);
    assert.equal(locale.sourceOpenSearch, undefined);
  }
});

test("HOME-001 preserves Home business data and live state boundaries", () => {
  for (const contract of [
    "listProjects(apiFetch)",
    "getApprovalSummary(apiFetch)",
    "listPendingApprovals(apiFetch)",
    'getReportSummary(apiFetch, { topic: "system_overview" })',
    'role="alert"',
    't("homeActiveProjectsPanel")',
    't("reviewQueue")'
  ]) {
    assert.match(home, new RegExp(contract.replace(/[(){}[\].?+*^$|\\]/g, "\\$&")));
  }

  assert.match(systemWorkspace, /systemStatus|SystemStatus|health|readiness/i);
  assert.match(css, /\.policy-strip/);
});
