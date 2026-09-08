import { describe, expect, it } from "vitest";
import type { ProjectGraphResponse } from "../src/lib/api";
import { versionGraphEvidence } from "../src/lib/versionGraphEvidence";

// Pure transformation tests, not a simulated network/backend adapter.
function graph(): ProjectGraphResponse {
  return { project_id: "project", node_limit: 120, truncated: false,
    nodes: [
      { id: "version", type: "DocumentVersion", label: "v1", metadata: {} },
      { id: "chunk", type: "Chunk", label: "Chunk", metadata: { chunk_index: 2, content: "Original", display_markdown: "**Original**", markdown_content: "**Original**", content_type: "table" } },
      { id: "hidden-chunk", type: "Chunk", label: "Unrelated", metadata: {} },
      { id: "tag:uuid", type: "Tag", label: "Shared", metadata: { technical_id: "uuid" } },
    ],
    edges: [
      { id: "vc", type: "VERSION_HAS_CHUNK", source: "version", target: "chunk" },
      { id: "vt", type: "VERSION_HAS_TAG", source: "version", target: "tag:uuid", metadata: { source: "manual" } },
      { id: "ct", type: "CHUNK_HAS_TAG", source: "chunk", target: "tag:uuid", metadata: { source: "llm" } },
    ] };
}

describe("CHG-292 actual graph evidence presentation", () => {
  it("preserves canonical identity and per-assignment provenance", () => {
    const evidence = versionGraphEvidence(graph(), "version", "Document");
    expect(evidence.documentTags).toEqual([{ id: "uuid", text: "Shared", source: "manual" }]);
    expect(evidence.chunks).toHaveLength(1);
    expect(evidence.chunks[0]).toMatchObject({ chunkIndex: 2, type: "table", content: "Original", displayMarkdown: "**Original**",
      tagDetails: [{ id: "uuid", text: "Shared", source: "llm" }] });
  });
  it("never copies document tags into chunks or invents a missing edge", () => {
    const input = graph();
    input.edges = input.edges.filter((edge) => edge.type !== "CHUNK_HAS_TAG");
    const evidence = versionGraphEvidence(input, "version", "Document");
    expect(evidence.documentTags).toHaveLength(1);
    expect(evidence.chunks[0].tags).toEqual([]);
    expect(evidence.chunks[0].tagDetails).toEqual([]);
  });
  it("rejects unrelated nodes and safely handles truncated/missing target nodes", () => {
    const input = graph();
    input.nodes = input.nodes.filter((node) => node.type !== "Tag");
    input.truncated = true;
    expect(versionGraphEvidence(input, "version", "Document").documentTags).toEqual([]);
    expect(versionGraphEvidence(input, "another-version", "Document").chunks).toEqual([]);
  });
  it("handles old optional metadata without fabricating content or source", () => {
    const input = graph();
    input.nodes[1].metadata = {};
    input.nodes[3].metadata = {};
    input.edges[2].metadata = {};
    const chunk = versionGraphEvidence(input, "version", "Document").chunks[0];
    expect(chunk).toMatchObject({ content: "", type: "text", displayMarkdown: null, markdownContent: null, chunkIndex: 0,
      tagDetails: [{ id: "uuid", text: "Shared", source: null }] });
  });
});
