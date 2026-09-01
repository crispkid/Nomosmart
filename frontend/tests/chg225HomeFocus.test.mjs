import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const home = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const zh = JSON.parse(readFileSync(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"));
const en = JSON.parse(readFileSync(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8"));

test("HOME-002 removes the complete Today Focus panel and dead presentation", () => {
  assert.doesNotMatch(home, /homeTodayFocus|focus-row|UploadCloud/);
  assert.doesNotMatch(css, /\.focus-row/);
  assert.equal((home.match(/<Panel\b/g) ?? []).length, 2);

  for (const locale of [zh, en]) {
    assert.equal(locale.homeTodayFocus, undefined);
    assert.equal(locale.homeTodayFocusTitle, undefined);
    assert.equal(locale.homeTodayFocusHelp, undefined);
  }
});

test("HOME-002 preserves live Home business sections and grouped CSS peers", () => {
  for (const contract of [
    "listProjects(apiFetch)",
    "getApprovalSummary(apiFetch)",
    "listPendingApprovals(apiFetch)",
    'getReportSummary(apiFetch, { topic: "system_overview" })',
    't("activeProjects")',
    't("processing")',
    't("pendingApprovals")',
    't("successRate")',
    't("homeActiveProjectsPanel")',
    't("reviewQueue")',
    'role="alert"'
  ]) {
    assert.match(home, new RegExp(contract.replace(/[(){}[\].?+*^$|\\]/g, "\\$&")));
  }

  assert.doesNotMatch(home, /DataSourceStrip/);
  assert.match(css, /\.row-title,/);
  assert.match(css, /\.chat-test,/);
  assert.match(css, /\.sync-card/);
});
