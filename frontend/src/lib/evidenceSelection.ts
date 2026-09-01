export type SourceMappedChunk = { id: string; sourceAnchor: string };

export function chunkIdsForSource(chunks: SourceMappedChunk[], sourceAnchor: string) {
  return chunks.filter((chunk) => chunk.sourceAnchor === sourceAnchor).map((chunk) => chunk.id);
}

export function toggleSingleChunkSelection(selectedChunkIds: string[], chunkId: string) {
  return selectedChunkIds.length === 1 && selectedChunkIds[0] === chunkId ? [] : [chunkId];
}
