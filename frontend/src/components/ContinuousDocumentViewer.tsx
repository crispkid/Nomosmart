"use client";

import { type KeyboardEvent, type MouseEvent } from "react";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { SourceRangeHighlights } from "@/components/SourceRangeHighlights";
import type { SourceSelectionGroup } from "@/lib/markdownSourceMapping";
import { pointerSourceRange } from "@/lib/sourceRangeGeometry";

export function ContinuousDocumentViewer({ source, selectionGroups, sourceActionLabel, onSelectRange }: {
  source: string;
  selectionGroups: SourceSelectionGroup[];
  sourceActionLabel: string;
  onSelectRange: (range: { start: number; end: number }) => void;
}) {
  function select(event: MouseEvent<HTMLElement>) {
    if (window.getSelection()?.isCollapsed === false) return;
    if (event.target instanceof Element && event.target.closest("a,button,input")) return;
    const range = pointerSourceRange(event.target, event.clientX, event.clientY);
    if (range) onSelectRange(range);
  }
  function activate(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (!(event.target instanceof HTMLElement) || event.target.closest("a,button,input")) return;
    const block = event.target.closest<HTMLElement>("[data-source-block-start][data-source-block-end]");
    if (!block) return;
    const start = Number(block.dataset.sourceBlockStart), end = Number(block.dataset.sourceBlockEnd);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || end <= start) return;
    event.preventDefault();
    onSelectRange({ start, end });
  }
  return <article className="continuous-document" onClick={select} onKeyDown={activate}>
    <SourceRangeHighlights groups={selectionGroups}>
      <SafeMarkdown className="continuous-document-content" source={source} sourceOffset={0} sourceActionLabel={sourceActionLabel} />
    </SourceRangeHighlights>
  </article>;
}
