

export function toggleSingleChunkSelection(selectedChunkIds: string[], chunkId: string) {
  return selectedChunkIds.length === 1 && selectedChunkIds[0] === chunkId ? [] : [chunkId];
}
