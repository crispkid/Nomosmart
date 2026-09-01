import assert from "node:assert/strict";
import test from "node:test";
import { chunkIdsForSource, toggleSingleChunkSelection } from "../src/lib/evidenceSelection.ts";

const mappedChunks = [
  { id: "C-001", sourceAnchor: "section-2-1" },
  { id: "C-002", sourceAnchor: "section-2-1" },
  { id: "C-003", sourceAnchor: "table-2-2" }
];

test("source selection returns every matching chunk without unrelated evidence", () => {
  assert.deepEqual(chunkIdsForSource(mappedChunks, "section-2-1"), ["C-001", "C-002"]);
  assert.deepEqual(chunkIdsForSource(mappedChunks, "missing"), []);
});

test("single chunk selection toggles off and replaces multi-source focus", () => {
  assert.deepEqual(toggleSingleChunkSelection([], "C-001"), ["C-001"]);
  assert.deepEqual(toggleSingleChunkSelection(["C-001"], "C-001"), []);
  assert.deepEqual(toggleSingleChunkSelection(["C-001", "C-002"], "C-002"), ["C-002"]);
});
