/** Convert a DOM range to canonical code-point offsets using renderer evidence. */
export function mappedSelectionRange(range: Range): { start: number; end: number } | null {
  const envelopes: { start: number; end: number; visibleStart: number; visibleEnd: number }[] = [];
  function endpoint(container: Node, offset: number, atEnd: boolean): number | null {
    const element = container.nodeType === Node.ELEMENT_NODE ? container as Element : container.parentElement;
    const leaf = element?.closest<HTMLElement>("[data-source-start][data-source-end]");
    if (!leaf) return null;
    const before = document.createRange();
    before.selectNodeContents(leaf);
    before.setEnd(container, offset);
    const relative = Array.from(before.toString()).length;
    const visibleLength = Array.from(leaf.textContent ?? "").length;
    const start = Number(leaf.dataset.sourceStart), end = Number(leaf.dataset.sourceEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) return null;
    if (relative < 0 || relative > visibleLength) return null;
    try { envelopes.push(...JSON.parse(leaf.dataset.sourceEnvelopes ?? "[]")); } catch { return null; }
    if (leaf.dataset.sourceDirect === "true") return start + relative;
    // Escapes/entities may occupy more source characters than visible glyphs.
    // Whole-leaf endpoints are exact; ambiguous interior endpoints are refused.
    if (!atEnd && relative === 0) return start;
    if (atEnd && relative === visibleLength) return end;
    return null;
  }
  const start = endpoint(range.startContainer, range.startOffset, false);
  const end = endpoint(range.endContainer, range.endOffset, true);
  if (start === null || end === null || end <= start) return null;
  let expandedStart = start, expandedEnd = end;
  for (const item of envelopes) {
    if (![item.start, item.end, item.visibleStart, item.visibleEnd].every(Number.isSafeInteger)
        || item.start < 0 || item.start > item.visibleStart || item.end < item.visibleEnd) return null;
    if (start <= item.visibleStart && end >= item.visibleEnd) {
      if (start === item.visibleStart) expandedStart = Math.min(expandedStart, item.start);
      if (end === item.visibleEnd) expandedEnd = Math.max(expandedEnd, item.end);
    }
  }
  return { start: expandedStart, end: expandedEnd };
}
