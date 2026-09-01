import assert from "node:assert/strict";
import test from "node:test";
import { buildMarkdownSourceSegments, chunkIdsForResolvedSourceAnchor, codePointLength, markdownArtifactReasonKey, resolvedSourceMappings } from "../src/lib/markdownSourceMapping.ts";

test("CHG-273 parses only explicit resolved Unicode mappings", () => {
  const mappings = resolvedSourceMappings([
    { mapping_status: "resolved", offset_unit: "unicode_code_point", source_anchor: "paragraph-1", markdown_start_offset: 0, markdown_end_offset: 3, anchor_start_offset: 0, anchor_end_offset: 3 },
    { mapping_status: "unresolved", source_anchor: "paragraph-2" }
  ]);
  assert.deepEqual(mappings, [{ sourceAnchor: "paragraph-1", markdownStart: 0, markdownEnd: 3, anchorStart: 0, anchorEnd: 3 }]);
});

test("CHG-273 segments preserve exact source and Unicode code points", () => {
  const source = "A🚀B\n\n# Title";
  const chunks = [
    { id: "chunk-1", sourceMappings: [{ sourceAnchor: "paragraph-1", markdownStart: 0, markdownEnd: 3, anchorStart: 0, anchorEnd: 3 }] },
    { id: "chunk-2", sourceMappings: [{ sourceAnchor: "paragraph-2", markdownStart: 5, markdownEnd: 12, anchorStart: 0, anchorEnd: 7 }] }
  ];
  const segments = buildMarkdownSourceSegments(source, chunks);
  assert.equal(segments.map((segment) => segment.text).join(""), source);
  assert.equal(codePointLength(source), 12);
  assert.deepEqual(segments.filter((segment) => segment.chunkIds.length).map((segment) => segment.chunkIds), [["chunk-1"], ["chunk-2"]]);
});

test("CHG-273 keeps same-range chunks as many-to-many selection", () => {
  const source = "Shared";
  const mapping = { sourceAnchor: "paragraph-1", markdownStart: 0, markdownEnd: 6, anchorStart: 0, anchorEnd: 6 };
  const segments = buildMarkdownSourceSegments(source, [{ id: "one", sourceMappings: [mapping] }, { id: "two", sourceMappings: [mapping] }]);
  assert.deepEqual(segments[0].chunkIds, ["one", "two"]);
  assert.deepEqual(chunkIdsForResolvedSourceAnchor([{ id: "one", sourceMappings: [mapping] }, { id: "two", sourceMappings: [mapping] }], "paragraph-1"), ["one", "two"]);
});

test("CHG-273 maps every artifact failure reason to localized UI copy", () => {
  assert.equal(markdownArtifactReasonKey("markdown_artifact_pending"), "markdownArtifactPending");
  assert.equal(markdownArtifactReasonKey("markdown_artifact_step_failed"), "markdownArtifactFailed");
  assert.equal(markdownArtifactReasonKey("markdown_artifact_invalid"), "markdownArtifactInvalid");
  assert.equal(markdownArtifactReasonKey("markdown_artifact_version_mismatch"), "markdownArtifactVersionMismatch");
  assert.equal(markdownArtifactReasonKey("markdown_artifact_missing"), "markdownArtifactMissing");
});
