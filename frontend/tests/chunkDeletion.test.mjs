import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/page.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const zh = readFileSync(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8");
const en = readFileSync(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8");

test("CHG-217 exposes a confirmed accessible permanent chunk deletion action", () => {
  assert.match(api, /export async function deleteKnowledgeChunk/);
  assert.match(api, /chunks\/\$\{chunkId\}\?lock_version=\$\{lockVersion\}/);
  assert.match(api, /method: "DELETE"/);
  assert.match(page, /className="chunk-delete-button"/);
  assert.match(page, /<Trash2 size=\{17\}/);
  assert.match(page, /role="alertdialog"/);
  assert.match(page, /event\.stopPropagation\(\)/);
  assert.match(page, /liveDetail\.next_stage_allowed/);
  assert.match(page, /knowledgeDetailNoChunksTitle/);
  assert.match(css, /\.chunk-delete-button/);
  assert.match(css, /flex: 0 0 40px/);
});

test("CHG-217 keeps Traditional Chinese and English deletion states aligned", () => {
  for (const key of [
    "knowledgeDetailDeleteChunk",
    "knowledgeDetailDeleteChunkTitle",
    "knowledgeDetailConfirmDeleteChunk",
    "knowledgeDetailNoChunksTitle",
    "knowledgeDetailChunksRequired",
    "knowledgeDetailArtifactsNotReady",
  ]) {
    assert.match(zh, new RegExp(`"${key}"`));
    assert.match(en, new RegExp(`"${key}"`));
  }
});
