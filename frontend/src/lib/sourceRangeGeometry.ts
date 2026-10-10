import type { ResolvedSourceMapping } from "@/lib/markdownSourceMapping";

function bounds(leaf: HTMLElement) {
  const start = Number(leaf.dataset.sourceStart), end = Number(leaf.dataset.sourceEnd);
  return Number.isSafeInteger(start) && Number.isSafeInteger(end) && end > start ? { start, end } : null;
}

export function sourceTargetForMappings(root: HTMLElement | null | undefined, mappings: ResolvedSourceMapping[]) {
  if (!root) return null;
  return Array.from(root.querySelectorAll<HTMLElement>("[data-source-start][data-source-end]"))
    .find(leaf => {
      const range = bounds(leaf);
      return range && mappings.some(m => range.start < m.markdownEnd && range.end > m.markdownStart);
    }) ?? null;
}

function endpoint(leaf: HTMLElement, points: number): { node: Node; offset: number } | null {
  const walker = document.createTreeWalker(leaf, NodeFilter.SHOW_TEXT);
  let node: Node | null, last: Node | null = null;
  let remaining = points;
  while ((node = walker.nextNode())) {
    last = node;
    const value = node.textContent ?? "", length = Array.from(value).length;
    if (remaining <= length) return { node, offset: Array.from(value).slice(0, remaining).join("").length };
    remaining -= length;
  }
  return last && remaining === 0 ? { node: last, offset: last.textContent?.length ?? 0 } : null;
}

export function sourceRangeRects(leaf: HTMLElement, start: number, end: number, root: HTMLElement) {
  const source = bounds(leaf);
  if (!source || source.start >= end || source.end <= start) return [];
  const range = document.createRange();
  if (leaf.dataset.sourceDirect === "true") {
    const a = endpoint(leaf, Math.max(start, source.start) - source.start);
    const b = endpoint(leaf, Math.min(end, source.end) - source.start);
    if (!a || !b) return [];
    range.setStart(a.node, a.offset);
    range.setEnd(b.node, b.offset);
  } else {
    range.selectNodeContents(leaf);
  }
  return Array.from(range.getClientRects()).flatMap(rect => {
    let left = rect.left, top = rect.top, right = rect.right, bottom = rect.bottom;
    let parent = leaf.parentElement;
    while (parent && parent !== root) {
      const style = getComputedStyle(parent), box = parent.getBoundingClientRect();
      if (style.overflowX !== "visible") {
        left = Math.max(left, box.left + parent.clientLeft);
        right = Math.min(right, box.left + parent.clientLeft + parent.clientWidth);
      }
      if (style.overflowY !== "visible") {
        top = Math.max(top, box.top + parent.clientTop);
        bottom = Math.min(bottom, box.top + parent.clientTop + parent.clientHeight);
      }
      parent = parent.parentElement;
    }
    return right > left && bottom > top ? [{ left, top, width: right - left, height: bottom - top }] : [];
  });
}

export function pointerSourceRange(target: EventTarget | null, x: number, y: number): { start: number; end: number } | null {
  const leaf = target instanceof Element ? target.closest<HTMLElement>("[data-source-start][data-source-end]") : null;
  if (!leaf) return null;
  const source = bounds(leaf);
  if (!source) return null;
  if (leaf.dataset.sourceDirect !== "true") return source;
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  const caret = doc.caretPositionFromPoint?.(x, y);
  const legacy = !caret ? doc.caretRangeFromPoint?.(x, y) : null;
  const node = caret?.offsetNode ?? legacy?.startContainer, offset = caret?.offset ?? legacy?.startOffset;
  if (!node || offset == null || !leaf.contains(node)) return source;
  const before = document.createRange();
  before.selectNodeContents(leaf);
  before.setEnd(node, offset);
  const position = source.start + Array.from(before.toString()).length;
  const start = Math.max(source.start, Math.min(position, source.end - 1));
  return { start, end: start + 1 };
}
