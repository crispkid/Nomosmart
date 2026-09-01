import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("CHG-269 model inventory shows configuration Name and provider Model", async () => {
  const source = await read("../src/components/SystemManagementWorkspace.tsx");
  const inventoryStart = source.indexOf("!modelTableLoading && modelTableRows.length");
  const inventoryEnd = source.indexOf("!modelTableLoading && !modelTableRows.length", inventoryStart);
  const inventory = source.slice(inventoryStart, inventoryEnd);

  assert.ok(inventoryStart >= 0 && inventoryEnd > inventoryStart);
  assert.match(inventory, /<th>\{t\("systemName"\)\}<\/th>[\s\S]*<th>\{t\("systemModel"\)\}<\/th>/);
  assert.match(inventory, /<strong>\{model\.name\}<\/strong>/);
  assert.match(inventory, /aiModelProviderName\(model\.raw\?\.config\)/);
  assert.doesNotMatch(inventory, /\{model\.endpoint\}/);
  assert.doesNotMatch(inventory, /t\("labelEndpoint"\)/);
});

test("CHG-269 provider model normalization is strict and has an em-dash fallback", async () => {
  const helper = await read("../src/components/AIModelInventoryFields.ts");
  assert.match(helper, /const value = config\?\.model_name/);
  assert.match(helper, /typeof value !== "string"/);
  assert.match(helper, /value\.trim\(\)/);
  assert.match(helper, /missingProviderModelName = "—"/);
});

test("CHG-269 keeps localized Name and Model labels and preserves popup connection fields", async () => {
  const [source, zh, en] = await Promise.all([
    read("../src/components/SystemManagementWorkspace.tsx"),
    read("../src/i18n/locales/zh.json"),
    read("../src/i18n/locales/en.json"),
  ]);

  assert.match(zh, /"systemName": "名稱"/);
  assert.match(zh, /"systemModel": "模型"/);
  assert.match(en, /"systemName": "Name"/);
  assert.match(en, /"systemModel": "Model"/);
  assert.match(source, /<label><span>\{t\("labelEndpoint"\)\}<\/span><input[\s\S]*name="endpoint" required/);
  assert.match(source, /<label><span>\{t\("labelModelName"\)\}<\/span><input[\s\S]*name="model_name"/);
});
