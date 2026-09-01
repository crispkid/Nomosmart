import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const loadLocale = (file) => JSON.parse(read(file));

test("CHG-254 home KPI helpers use live-derived values and explicit states", () => {
  const page = read("frontend/src/app/page.tsx");
  const metrics = read("frontend/src/lib/homeMetrics.ts");
  assert.match(page, /countProjectsUpdatedToday/);
  assert.match(page, /pending_owner_review/);
  assert.match(metrics, /last_activity_at/);
  assert.match(metrics, /status === "active"/);
  assert.match(page, /homeActiveProjectsHelperMany/);
  assert.match(page, /homePendingApprovalsHelperMany/);
  assert.match(page, /homeKpiLoadingHelper/);
  assert.match(page, /homeKpiUnavailableHelper/);
  assert.doesNotMatch(page, /homeActiveProjectsHelper["'`\)]/);
  assert.doesNotMatch(page, /homePendingApprovalsHelper["'`\)]/);
});

test("CHG-254 locale contracts cover zero, one, many, loading, and unavailable helpers", () => {
  const zh = loadLocale("frontend/src/i18n/locales/zh.json");
  const en = loadLocale("frontend/src/i18n/locales/en.json");
  const keys = [
    "homeActiveProjectsHelperZero",
    "homeActiveProjectsHelperOne",
    "homeActiveProjectsHelperMany",
    "homePendingApprovalsHelperZero",
    "homePendingApprovalsHelperOne",
    "homePendingApprovalsHelperMany",
    "homeKpiLoadingHelper",
    "homeKpiUnavailableHelper",
  ];
  for (const key of keys) {
    assert.equal(typeof zh[key], "string", `zh missing ${key}`);
    assert.equal(typeof en[key], "string", `en missing ${key}`);
  }
  assert.equal(zh.homeActiveProjectsHelper, undefined);
  assert.equal(en.homeActiveProjectsHelper, undefined);
  assert.equal(zh.homePendingApprovalsHelper, undefined);
  assert.equal(en.homePendingApprovalsHelper, undefined);
  assert.match(zh.homeActiveProjectsHelperMany, /\{count\}/);
  assert.match(en.homeActiveProjectsHelperMany, /\{count\}/);
  assert.match(zh.homePendingApprovalsHelperMany, /\{count\}/);
  assert.match(en.homePendingApprovalsHelperMany, /\{count\}/);
});
