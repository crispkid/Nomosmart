"use client";

import { type CSSProperties, type KeyboardEvent, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  buildMarkdownSourceSegments,
  markdownSelectionRanges,
  sourceSelectionGroupsForChunks,
  type MarkdownMappedChunk,
} from "@/lib/markdownSourceMapping";

type SelectionOverlaySpec = {
  id: string;
  chunkId: string;
  start: number;
  end: number;
};

type SelectionOverlayRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

function sameRects(left: Record<string, SelectionOverlayRect>, right: Record<string, SelectionOverlayRect>) {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => {
    const a = left[key];
    const b = right[key];
    return Boolean(b) && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
  });
}

export function CanonicalMarkdownSource({
  source,
  chunks,
  selectedChunkIds,
  onSelectChunkIds
}: {
  source: string;
  chunks: MarkdownMappedChunk[];
  selectedChunkIds: string[];
  onSelectChunkIds?: (chunkIds: string[]) => void;
}) {
  const segments = useMemo(() => buildMarkdownSourceSegments(source, chunks), [chunks, source]);
  const selected = useMemo(() => new Set(selectedChunkIds), [selectedChunkIds]);
  const selectionGroups = useMemo(() => sourceSelectionGroupsForChunks(chunks, selectedChunkIds), [chunks, selectedChunkIds]);
  const overlaySpecs = useMemo<SelectionOverlaySpec[]>(() => selectionGroups.flatMap((group) => markdownSelectionRanges(group).map((range, index) => ({
    id: `${group.id}-range-${range.start}-${range.end}-${index}`,
    chunkId: group.id,
    start: range.start,
    end: range.end,
  }))), [selectionGroups]);
  const sourceRef = useRef<HTMLPreElement>(null);
  const [overlayRects, setOverlayRects] = useState<Record<string, SelectionOverlayRect>>({});

  useLayoutEffect(() => {
    const root = sourceRef.current;
    if (!root) return;
    let frame = 0;
    let disposed = false;

    const measure = () => {
      frame = 0;
      if (disposed) return;
      const rootRect = root.getBoundingClientRect();
      const mappedElements = Array.from(root.querySelectorAll<HTMLElement>(".canonical-markdown-range"));
      const next: Record<string, SelectionOverlayRect> = {};
      for (const spec of overlaySpecs) {
        const elements = mappedElements.filter((element) => {
          const ids = element.dataset.chunkIds?.split(" ") ?? [];
          const start = Number(element.dataset.markdownStart);
          const end = Number(element.dataset.markdownEnd);
          return ids.includes(spec.chunkId) && Number.isFinite(start) && Number.isFinite(end) && start < spec.end && end > spec.start;
        });
        const rects = elements.map((element) => element.getBoundingClientRect()).filter((rect) => rect.width > 0 && rect.height > 0);
        if (!rects.length) continue;
        const left = Math.min(...rects.map((rect) => rect.left));
        const top = Math.min(...rects.map((rect) => rect.top));
        const right = Math.max(...rects.map((rect) => rect.right));
        const bottom = Math.max(...rects.map((rect) => rect.bottom));
        next[spec.id] = {
          top: top - rootRect.top + root.scrollTop,
          left: left - rootRect.left + root.scrollLeft,
          width: right - left,
          height: bottom - top,
        };
      }
      setOverlayRects((current) => sameRects(current, next) ? current : next);
    };
    const schedule = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(root);
    window.addEventListener("resize", schedule);
    measure();
    document.fonts?.ready.then(schedule).catch(() => undefined);
    return () => {
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [overlaySpecs, segments]);

  function activate(event: KeyboardEvent<HTMLElement>, chunkIds: string[]) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onSelectChunkIds?.(chunkIds);
  }

  return (
    <pre className="canonical-markdown-source" data-canonical-markdown-source="true" ref={sourceRef}>
      <code>
        {segments.map((segment) => {
          if (!segment.chunkIds.length) return <span key={segment.id}>{segment.text}</span>;
          const active = segment.chunkIds.some((chunkId) => selected.has(chunkId));
          return (
            <span
              aria-current={active ? "true" : undefined}
              className={`canonical-markdown-range${active ? " source-active" : ""}`}
              data-chunk-ids={segment.chunkIds.join(" ")}
              data-markdown-end={segment.end}
              data-markdown-start={segment.start}
              data-source-anchor={segment.sourceAnchors.length === 1 ? segment.sourceAnchors[0] : undefined}
              key={segment.id}
              onClick={() => onSelectChunkIds?.(segment.chunkIds)}
              onKeyDown={(event) => activate(event, segment.chunkIds)}
              role={onSelectChunkIds ? "button" : undefined}
              tabIndex={onSelectChunkIds ? 0 : undefined}
            >
              {segment.text}
            </span>
          );
        })}
      </code>
      <span aria-hidden="true" className="canonical-markdown-selection-layer">
        {overlaySpecs.map((spec) => {
          const rect = overlayRects[spec.id];
          const style: CSSProperties | undefined = rect ? {
            height: rect.height,
            left: rect.left,
            top: rect.top,
            width: rect.width,
          } : undefined;
          return (
            <span
              className={`canonical-markdown-selection-group${rect ? " is-positioned" : ""}`}
              data-chunk-id={spec.chunkId}
              data-markdown-end={spec.end}
              data-markdown-start={spec.start}
              key={spec.id}
              style={style}
            />
          );
        })}
      </span>
    </pre>
  );
}
