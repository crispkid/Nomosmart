import assert from "node:assert/strict";
import test from "node:test";
import { buildDocumentGraph } from "../src/lib/documentGraph.ts";

const evidence = {
  documentTitle: "核心系統備援流程.md",
  version: "v3.0",
  documentTags: [
    { id: "tag-backup", text: "備援", source: "llm" },
    { id: "tag-governance", text: "治理", source: "manual" }
  ],
  chunks: [
    {
      chunkIndex: 1,
      content: "切換條件包含服務健康檢查與主管核准。",
      id: "C-101",
      type: "text",
      sourceLabel: "第 2 頁",
      tags: ["備援", "治理"],
      tagDetails: [
        { id: "tag-backup", text: "備援", source: "llm" },
        { id: "tag-governance", text: "治理", source: "manual" }
      ]
    },
    {
      chunkIndex: 2,
      content: "復原時限依服務等級設定。",
      id: "C-102",
      type: "table",
      sourceLabel: "第 4 頁",
      tags: ["備援"],
      tagDetails: [{ id: "tag-backup", text: "備援", source: "llm" }]
    }
  ]
};

test("builds task-scoped document, chunk, tag nodes and traceable edges", () => {
  const graph = buildDocumentGraph(evidence);
  assert.deepEqual(graph.nodes[0], {
    id: "document",
    label: "核心系統備援流程.md",
    detail: "Document · v3.0",
    type: "document",
    x: 50,
    y: 50
  });
  assert.equal(graph.nodes.filter((node) => node.type === "chunk").length, 2);
  assert.equal(graph.nodes.find((node) => node.id === "chunk-c-101").label, "切換條件包含服務健康檢查與主管核准。");
  assert.equal(graph.nodes.filter((node) => node.type === "tag").length, 2);
  assert.equal(graph.edges.length, 7);
  assert.ok(graph.edges.some(([source, target]) => source === "document" && target === "chunk-c-101"));
});

test("deduplicates tags and preserves mixed content types", () => {
  const graph = buildDocumentGraph(evidence);
  assert.deepEqual(graph.nodes.filter((node) => node.type === "chunk").map((node) => node.contentType), ["text", "table"]);
  assert.equal(graph.nodes.filter((node) => node.type === "tag" && node.label === "備援")[0].detail, "Document tag · 2 chunks · LLM");
});

test("relates document and chunk tags by canonical tag id instead of display text only", () => {
  const graph = buildDocumentGraph(evidence);
  const backupNode = graph.nodes.find((node) => node.type === "tag" && node.label === "備援");
  assert.ok(backupNode);
  assert.equal(backupNode.id, "tag-id-tag-backup");
  assert.ok(graph.edges.some(([source, target]) => source === "document" && target === backupNode.id));
  assert.ok(graph.edges.some(([source, target]) => source === "chunk-c-101" && target === backupNode.id));
  assert.ok(graph.edges.some(([source, target]) => source === "chunk-c-102" && target === backupNode.id));
});
