import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);

async function read(path) {
  return readFile(new URL(path, root), "utf8");
}

test("CHG-235 uses server-backed model filtering and pagination", async () => {
  const [api, workspace] = await Promise.all([
    read("frontend/src/lib/api.ts"),
    read("frontend/src/components/SystemManagementWorkspace.tsx")
  ]);

  assert.match(api, /export async function listModelsPage/);
  assert.match(api, /response\.headers\.get\("X-Total-Count"\)/);
  assert.match(workspace, /modelTablePageSize.*useState\(20\)/);
  assert.match(workspace, /<option value=\{20\}>20<\/option><option value=\{50\}>50<\/option><option value=\{100\}>100<\/option>/);
  assert.match(workspace, /modelTableType === "all" \? undefined : modelTableType/);
  assert.match(workspace, /setModelTablePage\(1\)/);
  assert.match(workspace, /modelTableRows\.map/);
});

test("CHG-235 keeps disable and delete as independent commands", async () => {
  const [api, workspace, zh, en, css] = await Promise.all([
    read("frontend/src/lib/api.ts"),
    read("frontend/src/components/SystemManagementWorkspace.tsx"),
    read("frontend/src/i18n/locales/zh.json").then(JSON.parse),
    read("frontend/src/i18n/locales/en.json").then(JSON.parse),
    read("frontend/src/app/globals.css")
  ]);

  assert.match(api, /confirmation_name: string; config_version: number/);
  assert.match(workspace, /updateModel\(apiFetch, model\.id, \{ is_active: false \}\)/);
  assert.match(workspace, /type: "model-delete"/);
  assert.match(workspace, /modelDeleteConfirmation !== modal\.model\.name/);
  assert.match(workspace, /<Trash2 size=\{14\} \/>\{t\("systemDelete"\)\}/);
  assert.match(workspace, /details\.dependencies/);
  assert.match(css, /\.model-delete-warning/);
  assert.match(css, /\.model-list-pagination/);

  for (const messages of [zh, en]) {
    for (const key of [
      "systemModelTypeFilter",
      "systemRowsPerPage",
      "systemDeleteModelTitle",
      "systemDeleteModelWarningHelp",
      "systemDeleteModelConfirmationLabel",
      "systemModelDependencyProject"
    ]) assert.equal(typeof messages[key], "string", `${key} must be localized`);
  }
});

test("CHG-235 backend preserves historical rows and excludes tombstones from normal lists", async () => {
  const [route, model, migration] = await Promise.all([
    read("backend/app/api/routes/models.py"),
    read("backend/app/db/models.py"),
    read("sql/migrations/V029__ai_model_soft_delete.sql")
  ]);

  assert.match(route, /AIModel\.deleted_at\.is_\(None\)/);
  assert.match(route, /response\.headers\["X-Total-Count"\]/);
  assert.match(route, /with_for_update\(\)/);
  assert.match(route, /model\.api_key_encrypted = None/);
  assert.match(route, /model\.api_key_secret_ref = None/);
  assert.match(route, /active_chat_pairing/);
  assert.match(model, /deleted_at: Mapped\[datetime \| None\]/);
  assert.match(migration, /WHERE deleted_at IS NULL/);
  assert.doesNotMatch(route, /session\.delete\(model\)/);
});
