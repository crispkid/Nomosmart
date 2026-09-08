import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { CHUNK_GRAPH_PREVIEW_LENGTH, chunkContentPreview, chunkGraphTitle } from "../src/lib/documentGraph.ts";

test("normalizes preview whitespace without changing the supplied content", () => {
  const content = "  第一行\n\t第二行  ";
  assert.equal(chunkContentPreview(content), "第一行 第二行");
  assert.equal(content, "  第一行\n\t第二行  ");
  assert.equal(CHUNK_GRAPH_PREVIEW_LENGTH, 24);
});

test("uses exactly 24 grapheme clusters and appends one ellipsis only when needed", () => {
  assert.equal(chunkContentPreview("甲".repeat(24)), "甲".repeat(24));
  assert.equal(chunkContentPreview("甲".repeat(25)), `${"甲".repeat(24)}…`);

  const family = "👨‍👩‍👧‍👦";
  assert.equal(chunkContentPreview(`${"字".repeat(23)}${family}尾`), `${"字".repeat(23)}${family}…`);
  const combined = "e\u0301";
  assert.equal(chunkContentPreview(`${"字".repeat(23)}${combined}尾`), `${"字".repeat(23)}${combined}…`);
});

test("uses only the localized caller fallback when content is blank", () => {
  assert.equal(chunkContentPreview(" \n\t "), null);
  assert.equal(chunkGraphTitle(null, "切片 #7"), "切片 #7");
  assert.equal(chunkGraphTitle("內容", "切片 #7"), "內容");
});

test("wires both graph surfaces to explicit content/index inspector fields", async () => {
  const [documentGraph, projectGraph, explorer, knowledgePage, approvalPage, english, chinese, css] = await Promise.all([
    readFile(new URL("../src/components/DocumentGraphPreview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/ProjectGraphPreview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/GraphExplorer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/project/[id]/knowledge/[knowledgeId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/app/approve/[approvalTaskId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/en.json", import.meta.url), "utf8"),
    readFile(new URL("../src/i18n/locales/zh.json", import.meta.url), "utf8"),
    readFile(new URL("../src/app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.match(documentGraph, /chunkContent: chunk\.content/);
  assert.match(documentGraph, /chunkDisplayMarkdown: chunk\.displayMarkdown/);
  assert.match(documentGraph, /chunkIndex: chunk\.chunkIndex/);
  assert.match(documentGraph, /chunkMarkdownContent: chunk\.markdownContent/);
  assert.match(documentGraph, /chunkGraphTitle\(chunk\.content/);
  assert.doesNotMatch(documentGraph, /title: chunk\.title/);
  assert.match(projectGraph, /metadataContent\(chunk\.metadata\)/);
  assert.match(projectGraph, /metadataMarkdown\(chunk\.metadata, "display_markdown"\)/);
  assert.match(projectGraph, /chunkGraphTitle\(content/);
  assert.doesNotMatch(projectGraph, /`#\$\{chunkIndex \+ 1\}/);
  assert.match(explorer, /data-graph-chunk-number="true"/);
  assert.match(explorer, /data-graph-chunk-content="true"/);
  assert.match(explorer, /<ChunkMarkdownView/);
  assert.match(explorer, /role="region"/);
  assert.doesNotMatch(explorer, /dangerouslySetInnerHTML/);
  // CHG-292: the knowledge dialog gets scoped graph evidence from the API;
  // content/index/display fields must survive that adapter, not a PG-tag redraw.
  assert.match(knowledgePage, /<VersionGraphPreview/);
  const versionEvidence = await readFile(new URL("../src/lib/versionGraphEvidence.ts", import.meta.url), "utf8");
  const versionPreview = await readFile(new URL("../src/components/VersionGraphPreview.tsx", import.meta.url), "utf8");
  assert.match(versionPreview, /getDocumentVersionGraph\(apiFetch/);
  assert.match(versionEvidence, /chunkIndex: Number\(metadata\.chunk_index/);
  assert.match(versionEvidence, /content: typeof metadata\.content/);
  assert.match(versionEvidence, /displayMarkdown: typeof metadata\.display_markdown/);
  assert.match(approvalPage, /chunkIndex: chunk\.index/);
  assert.match(approvalPage, /displayMarkdown: chunk\.display_markdown/);
  assert.match(english, /"graphDetailChunkNumber": "Number"/);
  assert.match(english, /"graphDetailChunkFullContent": "Full content"/);
  assert.match(chinese, /"graphDetailChunkNumber": "編號"/);
  assert.match(chinese, /"graphDetailChunkFullContent": "完整內容"/);
  assert.match(css, /white-space: pre-wrap/);
  assert.match(css, /max-height: 260px/);
});
