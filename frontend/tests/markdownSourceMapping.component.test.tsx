import { describe, expect, it, vi } from "vitest";

import {
  buildMarkdownSourceSegments,
  chunkIdsForResolvedSourceAnchor,
  codePointLength,
  firstMarkdownRangeForChunk,
  markdownSelectionRanges,
  markdownArtifactReasonKey,
  resolvedSourceMappings,
  sourceAnchorsForChunks,
  sourceSelectionGroupsForChunks,
  sourceSelectionScrollBehavior,
} from "@/lib/markdownSourceMapping";

describe("CHG-273 canonical Markdown source mapping", () => {
  it("accepts only complete resolved Unicode mappings", () => {
    expect(resolvedSourceMappings([
      null,
      "invalid",
      { mapping_status: "unresolved", offset_unit: "unicode_code_point" },
      { mapping_status: "resolved", offset_unit: "utf16" },
      { mapping_status: "resolved", offset_unit: "unicode_code_point", source_anchor: "", markdown_start_offset: 0, markdown_end_offset: 1, anchor_start_offset: 0, anchor_end_offset: 1 },
      { mapping_status: "resolved", offset_unit: "unicode_code_point", source_anchor: "p", markdown_start_offset: -1, markdown_end_offset: 1, anchor_start_offset: 0, anchor_end_offset: 1 },
      { mapping_status: "resolved", offset_unit: "unicode_code_point", source_anchor: "p", markdown_start_offset: 1, markdown_end_offset: 1, anchor_start_offset: 0, anchor_end_offset: 1 },
      { mapping_status: "resolved", offset_unit: "unicode_code_point", source_anchor: "p", markdown_start_offset: 0, markdown_end_offset: 2, anchor_start_offset: 0, anchor_end_offset: 2 },
    ])).toEqual([{ sourceAnchor: "p", markdownStart: 0, markdownEnd: 2, anchorStart: 0, anchorEnd: 2 }]);
  });

  it("segments overlapping ranges without changing Unicode source text", () => {
    const source = "A🚀BCD";
    const chunks = [
      { id: "one", sourceMappings: [{ sourceAnchor: "p1", markdownStart: 0, markdownEnd: 3, anchorStart: 0, anchorEnd: 3 }] },
      { id: "two", sourceMappings: [{ sourceAnchor: "p1", markdownStart: 2, markdownEnd: 5, anchorStart: 2, anchorEnd: 5 }] },
      { id: "outside", sourceMappings: [{ sourceAnchor: "p2", markdownStart: 8, markdownEnd: 10, anchorStart: 0, anchorEnd: 2 }] },
    ];
    const segments = buildMarkdownSourceSegments(source, chunks);
    expect(segments.map((segment) => segment.text).join("")).toBe(source);
    expect(segments.map((segment) => segment.chunkIds)).toEqual([["one"], ["one", "two"], ["two"]]);
    expect(segments[1].sourceAnchors).toEqual(["p1"]);
    expect(codePointLength(source)).toBe(5);
    expect(buildMarkdownSourceSegments("", chunks)).toEqual([]);
  });

  it("resolves range, selected anchors and all artifact reason keys", () => {
    const mapping = { sourceAnchor: "p1", markdownStart: 0, markdownEnd: 2, anchorStart: 0, anchorEnd: 2 };
    const chunks = [{ id: "one", sourceMappings: [mapping] }, { id: "two", sourceMappings: [{ ...mapping, sourceAnchor: "p2" }] }];
    expect(firstMarkdownRangeForChunk(chunks[0])).toEqual(mapping);
    expect(firstMarkdownRangeForChunk(undefined)).toBeNull();
    expect([...sourceAnchorsForChunks(chunks, ["one", "missing"])]).toEqual(["p1"]);
    expect(chunkIdsForResolvedSourceAnchor(chunks, "p2")).toEqual(["two"]);
    expect(chunkIdsForResolvedSourceAnchor(chunks, "missing")).toEqual([]);
    expect(markdownArtifactReasonKey("markdown_artifact_pending")).toBe("markdownArtifactPending");
    expect(markdownArtifactReasonKey("markdown_artifact_step_failed")).toBe("markdownArtifactFailed");
    expect(markdownArtifactReasonKey("markdown_artifact_version_mismatch")).toBe("markdownArtifactVersionMismatch");
    expect(markdownArtifactReasonKey("markdown_artifact_invalid")).toBe("markdownArtifactInvalid");
    expect(markdownArtifactReasonKey(null)).toBe("markdownArtifactMissing");
  });

  it("merges only overlapping or adjacent ranges within the same selected Chunk", () => {
    const chunks = [{
      id: "one",
      sourceMappings: [
        { sourceAnchor: "p1", markdownStart: 2, markdownEnd: 5, anchorStart: 0, anchorEnd: 3 },
        { sourceAnchor: "p2", markdownStart: 5, markdownEnd: 8, anchorStart: 0, anchorEnd: 3 },
        { sourceAnchor: "p3", markdownStart: 12, markdownEnd: 15, anchorStart: 0, anchorEnd: 3 },
      ],
    }];
    const [group] = sourceSelectionGroupsForChunks(chunks, ["one"]);
    expect(group.sourceAnchors).toEqual(["p1", "p2", "p3"]);
    expect(markdownSelectionRanges(group)).toEqual([{ start: 2, end: 8 }, { start: 12, end: 15 }]);
  });

  it("disables smooth selection scrolling for reduced-motion users", () => {
    const matchMedia = vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    }));
    expect(sourceSelectionScrollBehavior()).toBe("auto");
    matchMedia.mockRestore();
    expect(sourceSelectionScrollBehavior()).toBe("smooth");
  });
});
