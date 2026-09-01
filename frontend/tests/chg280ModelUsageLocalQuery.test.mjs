import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function sources() {
  return Promise.all([
    readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse)
  ]);
}

function modelFilterSource(page) {
  const start = page.indexOf("function ModelFilterBar");
  const end = page.indexOf("function ReportEmptyState", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return page.slice(start, end);
}

test("CHG-280 adds a models-only local Query action wired to the shared query boundary", async () => {
  const [page] = await sources();
  assert.match(
    page,
    /activeTab === "models" \? <ModelFilterBar filters=\{draftFilters\} loading=\{queryLoading\} onChange=\{setDraftFilters\} onQuery=\{applyQuery\} \/>/
  );

  const modelFilter = modelFilterSource(page);
  assert.equal((modelFilter.match(/<select/g) ?? []).length, 4);
  assert.equal((modelFilter.match(/<button/g) ?? []).length, 1);
  assert.ok(modelFilter.lastIndexOf("<button") > modelFilter.lastIndexOf("<select"));
  assert.match(modelFilter, /disabled=\{loading\}/);
  assert.match(modelFilter, /onClick=\{\(\) => \{ void onQuery\(\); \}\}/);
  assert.match(modelFilter, /<Search size=\{16\} \/>/);
  assert.match(modelFilter, /loading \? t\("reportQueryLoading"\) : t\("reportQuery"\)/);
  assert.doesNotMatch(modelFilter, /onChange=\{[^}]*onQuery/);

  const applyStart = page.indexOf("async function applyQuery()");
  const applyEnd = page.indexOf("async function changeTab", applyStart);
  const applyQuery = page.slice(applyStart, applyEnd);
  assert.match(applyQuery, /if \(queryLoading\) return;/);
  assert.match(applyQuery, /setAppliedFilters\(draftFilters\)/);
  assert.equal((applyQuery.match(/queryTab\(activeTab, draftFilters, true\)/g) ?? []).length, 1);
});

test("CHG-280 preserves the global Query action and aligned bilingual labels", async () => {
  const [page, , zh, en] = await sources();
  const beforeModels = page.slice(0, page.indexOf("function ModelFilterBar"));
  assert.match(beforeModels, /className="action-button report-query-button"/);
  assert.equal(zh.reportQuery, "查詢");
  assert.equal(en.reportQuery, "Query");
  assert.equal(zh.reportQueryLoading, "查詢中…");
  assert.equal(en.reportQueryLoading, "Querying…");
});

test("CHG-280 gives the local action a desktop right column and inherited narrow layout", async () => {
  const [, css] = await sources();
  assert.match(css, /\.report-model-filter-bar\s*\{[\s\S]*?grid-template-columns:\s*repeat\(4, minmax\(160px, 1fr\)\) auto;/);
  assert.match(css, /\.report-filter-bar \.action-button\s*\{\s*grid-column:\s*1 \/ -1;/);
  assert.match(css, /\.report-filter-bar \.action-button\s*\{\s*width:\s*100%;/);
  assert.match(css, /\.report-query-button\s*\{[\s\S]*?min-width:\s*110px;/);
});
