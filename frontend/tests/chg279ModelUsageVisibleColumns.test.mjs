import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const hiddenOnScreen = [
  "provider_reported_cost",
  "embedding_tokens",
  "ocr_pages",
  "cost_source"
];

const expectedVisible = [
  "model_type",
  "ai_model_name",
  "provider",
  "project_name",
  "usage_purpose",
  "call_count",
  "success_count",
  "failure_count",
  "total_tokens",
  "estimated_cost",
  "currency",
  "avg_latency_ms",
  "error_rate"
];

function arrayFields(source, marker) {
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `Missing ${marker}`);
  const line = source.slice(start, source.indexOf("\n", start));
  return [...line.matchAll(/"([a-z0-9_]+)"/g)].map((match) => match[1]);
}

test("CHG-279 hides only the four requested model-usage table columns", async () => {
  const page = await readFile(new URL("../src/app/reports/page.tsx", import.meta.url), "utf8");
  const start = page.indexOf("function ModelPanel");
  const end = page.indexOf("function AlertPanel", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const modelPanel = page.slice(start, end);
  const visible = [...modelPanel.matchAll(/\["([a-z0-9_]+)",/g)].map((match) => match[1]);

  assert.deepEqual(visible, expectedVisible);
  for (const field of hiddenOnScreen) assert.doesNotMatch(modelPanel, new RegExp(`\\["${field}"`));
});

test("CHG-279 preserves all four fields in Frontend and Backend CSV contracts", async () => {
  const [frontendExport, backendReports] = await Promise.all([
    readFile(new URL("../src/lib/reportExport.ts", import.meta.url), "utf8"),
    readFile(new URL("../../backend/app/api/routes/reports.py", import.meta.url), "utf8")
  ]);
  const frontendFields = arrayFields(frontendExport, "model_usage_metrics:");
  const backendFields = arrayFields(backendReports, '"model_usage_metrics":');

  for (const field of hiddenOnScreen) {
    assert.ok(frontendFields.includes(field), `Frontend CSV lost ${field}`);
    assert.ok(backendFields.includes(field), `Backend CSV lost ${field}`);
  }
  assert.match(backendReports, /"provider_reported_cost": "官方成本"/);
  assert.match(backendReports, /"embedding_tokens": "Embedding Token"/);
  assert.match(backendReports, /"ocr_pages": "OCR 頁數"/);
  assert.match(backendReports, /"cost_source": "成本來源"/);
  assert.match(backendReports, /"provider_reported_cost": "Provider-reported Cost"/);
  assert.match(backendReports, /"embedding_tokens": "Embedding Tokens"/);
  assert.match(backendReports, /"ocr_pages": "OCR Pages"/);
  assert.match(backendReports, /"cost_source": "Cost Source"/);
});
