import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


test("CHG-278 uses AIModel.name and removes the API-key reporting dimension", async () => {
  const [page, api, reportExport, zh, en, css] = await Promise.all([
    readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/lib/reportExport.ts", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8")
  ]);

  assert.match(page, /\["ai_model_name", t\("reportColModel"\)\]/);
  assert.doesNotMatch(page, /integrationClientId/);
  assert.doesNotMatch(page, /reportApiKeyFilter/);
  assert.match(page, /report-sticky-model-type/);
  assert.match(page, /report-sticky-model-name/);
  assert.doesNotMatch(api, /ModelUsageReportFilters[^\n]*integrationClientId/);
  assert.doesNotMatch(reportExport, /model_usage_metrics: \[[^\n]*("model_name"|"integration_client_id"|"api_key_prefix")/);
  assert.equal(zh.reportColModel, "模型名稱");
  assert.equal(en.reportColModel, "Model Name");
  assert.equal(zh.reportCostNotProvided, "未提供");
  assert.equal(en.reportCostNotProvided, "Not provided");
  assert.match(css, /\.report-sticky-model-type/);
  assert.match(css, /\.report-sticky-model-name/);
});
