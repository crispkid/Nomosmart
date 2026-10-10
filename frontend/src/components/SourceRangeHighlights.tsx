"use client";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { markdownSelectionRanges, type SourceSelectionGroup } from "@/lib/markdownSourceMapping";
import { sourceRangeRects } from "@/lib/sourceRangeGeometry";

type HighlightRect = { chunkId: string; left: number; top: number; width: number; height: number };

export function SourceRangeHighlights({ children, groups }: { children: ReactNode; groups: SourceSelectionGroup[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [rects, setRects] = useState<HighlightRect[]>([]);
  const selections = useMemo(() => groups.flatMap(group => markdownSelectionRanges(group).map(range => ({ ...range, chunkId: group.id }))), [groups]);
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    let frame = 0, disposed = false;
    const measure = () => {
      frame = 0;
      if (disposed) return;
      const box = root.getBoundingClientRect();
      const leaves = Array.from(root.querySelectorAll<HTMLElement>("[data-source-start][data-source-end]"));
      const next = selections.flatMap(selection => leaves.flatMap(leaf =>
        sourceRangeRects(leaf, selection.start, selection.end, root).map(rect => ({
          chunkId: selection.chunkId, left: rect.left - box.left, top: rect.top - box.top,
          width: rect.width, height: rect.height,
        }))));
      setRects(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
    };
    const schedule = () => { if (!disposed && !frame) frame = requestAnimationFrame(measure); };
    const observer = new ResizeObserver(schedule);
    observer.observe(root);
    root.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    document.fonts?.ready.then(schedule).catch(() => undefined);
    schedule();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      root.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [selections, children]);
  return <div className="source-range-root" ref={ref}>
    {children}
    {rects.map((rect, index) => <span aria-hidden="true" className="source-range-highlight" data-highlight-chunk-id={rect.chunkId} key={`${rect.chunkId}-${index}`} style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }} />)}
  </div>;
}
