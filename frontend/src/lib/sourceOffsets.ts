/** One linear UTF-16 -> Unicode code-point map for a complete source document. */
export function codePointOffsetMap(source: string) {
  const offsets = new Uint32Array(source.length + 1);
  let utf16 = 0, points = 0;
  for (const point of source) {
    for (let i = 0; i < point.length; i++) offsets[utf16 + i] = points;
    utf16 += point.length;
    offsets[utf16] = ++points;
  }
  return offsets;
}

/** Fenced code has exact literal positions; never locate a duplicate by text search. */
export function fencedCodeLiteralRange(source: string, start: number, end: number, value: string) {
  const raw = source.slice(start, end);
  const opening = /^ {0,3}(`{3,}|~{3,})[^\n]*\r?\n/.exec(raw);
  if (!opening) return null;
  const literalStart = start + opening[0].length;
  const literalEnd = literalStart + value.length;
  if (literalEnd > end || source.slice(literalStart, literalEnd) !== value) return null;
  const tail = source.slice(literalEnd, end);
  const marker = opening[1][0];
  const closing = new RegExp(`^\\r?\\n {0,3}${marker}{${opening[1].length},} *$`);
  if (tail !== "" && tail !== "\n" && !closing.test(tail)) return null;
  return { start: literalStart, end: literalEnd };
}
