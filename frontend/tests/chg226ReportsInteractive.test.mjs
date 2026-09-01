import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../src/app/reports/page.tsx", import.meta.url);
const apiPath = new URL("../src/lib/api.ts", import.meta.url);
const cssPath = new URL("../src/app/globals.css", import.meta.url);

test("REPORT-011 uses explicit draft/applied querying and complete tab topic maps", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /draftFilters/);
  assert.match(page, /appliedFilters/);
  assert.match(page, /reportFiltersPending/);
  assert.match(page, /queryTab\(activeTab, draftFilters, true\)/);
  assert.match(page, /references: \["project_reference_ranking", "document_reference_ranking"\]/);
  assert.match(page, /quality: \["rag_quality_metrics", "validation_run_metrics"\]/);
  assert.doesNotMatch(page, /exportTopic/);
});

test("REPORT-011 fixes server pagination at 20 and gives each table its own CSV action", async () => {
  const page = await readFile(pagePath, "utf8");
  const api = await readFile(apiPath, "utf8");
  assert.match(page, /const REPORT_PAGE_SIZE = 20/);
  assert.match(page, /function ReportPagination/);
  assert.match(page, /function ReportPanel/);
  assert.match(page, /downloadTopic\(topic\)/);
  assert.match(api, /getReportFilterOptions/);
  assert.match(api, /query\.set\("scope"/);
  assert.match(api, /query\.set\("page"/);
  assert.match(api, /query\.set\("page_size"/);
});

test("REPORT-011 renders scoped query and table loading states", async () => {
  const page = await readFile(pagePath, "utf8");
  const css = await readFile(cssPath, "utf8");
  assert.match(page, /report-query-loading/);
  assert.match(page, /report-table-loading/);
  assert.match(page, /activeTab === "models" \? <ModelFilterBar/);
  assert.match(css, /\.report-pagination/);
  assert.match(css, /\.report-panel-actions/);
});
