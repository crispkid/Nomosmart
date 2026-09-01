import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pageUrl = new URL("../src/app/reports/page.tsx", import.meta.url);
const apiUrl = new URL("../src/lib/api.ts", import.meta.url);
const cssUrl = new URL("../src/app/globals.css", import.meta.url);
const zhUrl = new URL("../src/i18n/locales/zh.json", import.meta.url);
const enUrl = new URL("../src/i18n/locales/en.json", import.meta.url);

const removedKeys = [
  "reportCsvOnlyHelp",
  "metricChatCount",
  "metricValidationRuns",
  "metricCitationCount",
  "metricAverageLatency",
  "reportBackendLiveSummary",
  "reportCsvValidationRuns",
  "reportChatCitationCount",
  "reportLiveChatLatency"
];

test("REPORT-013 removes the global CSV strip and cross-tab KPI cards", async () => {
  const [page, css, zh, en] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(cssUrl, "utf8"),
    readFile(zhUrl, "utf8").then(JSON.parse),
    readFile(enUrl, "utf8").then(JSON.parse)
  ]);

  for (const removed of [
    "report-csv-note",
    "report-stat-grid",
    "activePrimaryResponse",
    "liveMetric",
    "formatMetric",
    "<StatCard"
  ]) {
    assert.equal(page.includes(removed), false, `unexpected report artifact ${removed}`);
  }
  assert.doesNotMatch(css, /\.report-csv-note|\.report-stat-grid/);
  for (const key of removedKeys) {
    assert.equal(key in zh, false, `unexpected zh key ${key}`);
    assert.equal(key in en, false, `unexpected en key ${key}`);
  }
});

test("REPORT-013 preserves query tabs results pagination and scoped CSV", async () => {
  const [page, api] = await Promise.all([
    readFile(pageUrl, "utf8"),
    readFile(apiUrl, "utf8")
  ]);

  for (const retained of [
    "report-query-state",
    "report-topic-tabs",
    "report-query-loading",
    "report-results",
    "REPORT_PAGE_SIZE = 20",
    "ReportPagination",
    "ReportPanel",
    "downloadTopic(topic)",
    'activeTab === "models" ? <ModelFilterBar'
  ]) {
    assert.ok(page.includes(retained), `missing retained report behavior: ${retained}`);
  }
  assert.match(page, /downloadReportCsv\(apiFetch, \{ \.\.\.reportParams\(topic, appliedFilters\)/);
  assert.match(api, /metrics: ReportMetricCard\[\];/);
});
