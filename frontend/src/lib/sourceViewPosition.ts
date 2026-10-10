"use client";
import { useLayoutEffect, useRef, type RefObject } from "react";
import { pointerSourceRange } from "@/lib/sourceRangeGeometry";

export function useSourceViewPosition(viewer: RefObject<HTMLDivElement | null>, view: string, source: string | null | undefined, selectedCount: number) {
  const pending = useRef<{ source: string; offset: number } | null>(null);
  function remember() {
    pending.current = null;
    const root = viewer.current;
    if (!root || !source || selectedCount) return;
    const box = root.getBoundingClientRect();
    const leaves = Array.from(root.querySelectorAll<HTMLElement>("[data-source-start][data-source-end]"));
    const leaf = leaves.find(node => { const rect = node.getBoundingClientRect(); return rect.bottom > box.top + 24 && rect.top < box.bottom; });
    if (!leaf) return;
    const rect = leaf.getBoundingClientRect();
    const x = Math.max(box.left + 20, rect.left + 1), y = Math.max(box.top + 24, rect.top + 1);
    const range = pointerSourceRange(document.elementFromPoint(x, y), x, y);
    const offset = range?.start ?? Number(leaf.dataset.sourceStart);
    if (Number.isSafeInteger(offset) && offset >= 0) pending.current = { source, offset };
  }
  useLayoutEffect(() => {
    const location = pending.current;
    pending.current = null;
    const root = viewer.current;
    if (!root || !location || location.source !== source || selectedCount) return;
    const leaves = Array.from(root.querySelectorAll<HTMLElement>("[data-source-start][data-source-end]"));
    const leaf = leaves.find(node => Number(node.dataset.sourceEnd) > location.offset);
    if (!leaf) return;
    const range = document.createRange();
    let node: Node | null = null;
    if (leaf.dataset.sourceDirect === "true" && Number(leaf.dataset.sourceStart) <= location.offset) {
      const walker = document.createTreeWalker(leaf, NodeFilter.SHOW_TEXT);
      let remaining = location.offset - Number(leaf.dataset.sourceStart);
      while ((node = walker.nextNode())) {
        const points = Array.from(node.textContent ?? "");
        if (remaining <= points.length) { range.setStart(node, points.slice(0, remaining).join("").length); range.collapse(true); break; }
        remaining -= points.length;
      }
    }
    const rect = node ? range.getBoundingClientRect() : leaf.getBoundingClientRect();
    root.scrollTo({ top: root.scrollTop + rect.top - root.getBoundingClientRect().top - 24, behavior: "instant" });
  }, [view, source, selectedCount, viewer]);
  return remember;
}
