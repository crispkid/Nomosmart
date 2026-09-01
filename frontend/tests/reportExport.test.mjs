import assert from "node:assert/strict";
import test from "node:test";
import { buildCsv, buildLocalizedReportCsv, buildReportFilename, normalizeReportCsvLocale, reportTopics } from "../src/lib/reportExport.ts";

test("report export topics cover formal CSV-only report subjects", () => {
  const topics = reportTopics.map((topic) => topic.id);
  for (const required of [
    "system_overview",
    "project_ranking",
    "project_reference_ranking",
    "document_reference_ranking",
    "owner_project_summary",
    "document_pipeline_metrics",
    "rag_quality_metrics",
    "validation_run_metrics",
    "model_usage_metrics",
    "alert_metrics"
  ]) assert.equal(topics.includes(required), true);
});

test("report CSV uses UTF-8 BOM, stable fallback headers, escaping and unit-free numeric values", () => {
  const csv = buildCsv([
    { project_name: "法規,知識庫", success_rate: 0.94, note: "line\nbreak" },
    { project_name: "財務 \"內控\"", success_rate: 0.91, note: "ok" }
  ], ["project_name", "success_rate", "note"]);

  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.match(csv, /^﻿project_name,success_rate,note\r\n/);
  assert.match(csv, /"法規,知識庫",0\.94,"line\nbreak"/);
  assert.match(csv, /"財務 ""內控""",0\.91,ok/);
  assert.equal(csv.includes("94%"), false);
});

test("report CSV header titles follow current website language while values stay machine-friendly", () => {
  const rows = [{ project_name: "法規知識庫", success_rate: 0.94, qa_count: 2840 }];
  const zh = buildLocalizedReportCsv(rows, "project_ranking", "zh");
  const en = buildLocalizedReportCsv(rows, "project_ranking", "en");

  assert.match(zh, /^﻿排名,專案名稱,活躍文件,Pipeline 次數,問答次數,驗證批次數,30 天活躍使用者,成功率,失敗率\r\n/);
  assert.match(en, /^﻿Rank,Project name,Active documents,Pipeline runs,Q&A count,Validation runs,Active users 30d,Success rate,Failure rate\r\n/);
  assert.match(zh, /法規知識庫/);
  assert.match(en, /法規知識庫/);
  assert.equal(zh.includes("94%"), false);
  assert.equal(en.includes("94%"), false);
});

test("report CSV locale falls back to Traditional Chinese unless website language is English", () => {
  assert.equal(normalizeReportCsvLocale("en-US"), "en");
  assert.equal(normalizeReportCsvLocale("zh-Hant"), "zh");
  assert.equal(normalizeReportCsvLocale(undefined), "zh");
});

test("report CSV filename follows product topic and date pattern", () => {
  assert.equal(
    buildReportFilename("project_reference_ranking", "2026-06-01", "2026-06-27"),
    "nomosmart_project_reference_ranking_2026-06-01_2026-06-27.csv"
  );
});
