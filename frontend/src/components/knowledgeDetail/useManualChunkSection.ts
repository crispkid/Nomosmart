"use client";

import { useState, type RefObject } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ApiFetch, KnowledgeDetailResponse } from "@/lib/api";
import { createManualChunk } from "@/lib/api";
import { mappedSelectionRange } from "@/lib/manualSourceSelection";
import { codePointLength } from "@/lib/markdownSourceMapping";
import type { ArticleView, ManualTextSelection } from "./knowledgeDetailModel";

/** Page dependencies shared with the manual chunk section. */
export type ManualChunkDeps = {
  apiFetch: ApiFetch;
  params: { id: string; knowledgeId: string };
  liveDetail: KnowledgeDetailResponse | null;
  setLiveDetail: Dispatch<SetStateAction<KnowledgeDetailResponse | null>>;
  articleViewerRef: RefObject<HTMLDivElement | null>;
  markdownSourceText: string | null;
  setSelectedChunkIds: Dispatch<SetStateAction<string[]>>;
  setSourceLocationError: Dispatch<SetStateAction<boolean>>;
};

/** Manual chunk text selection, capture and submission (split from the knowledge detail page, OPT424-038). */
export function useManualChunkSection(deps: ManualChunkDeps) {
  const { apiFetch, params, liveDetail, setLiveDetail, articleViewerRef, markdownSourceText, setSelectedChunkIds, setSourceLocationError } = deps;
  const [manualSelection, setManualSelection] = useState<ManualTextSelection | null>(null);
  const [manualChunkBusy, setManualChunkBusy] = useState(false);
  const [manualChunkError, setManualChunkError] = useState(false);

  function captureManualSelection(viewMode: ArticleView) {
    if (!liveDetail?.manual_edit_enabled) return;
    const selection = window.getSelection();
    const viewer = articleViewerRef.current;
    if (!selection || !viewer || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (!viewer.contains(range.commonAncestorContainer)) return;
    const rawSelection = selection.toString();
    const content = rawSelection.trim();
    if (!content) {
      setManualSelection(null);
      return;
    }
    if (viewMode === "original") {
      const mapped = mappedSelectionRange(range);
      if (!mapped || !markdownSourceText) {
        setManualSelection(null);
        setSourceLocationError(true);
        return;
      }
      const raw = Array.from(markdownSourceText).slice(mapped.start, mapped.end).join("");
      const canonicalContent = raw.trim();
      if (!canonicalContent) return;
      const startOffset = mapped.start + codePointLength(raw.slice(0, raw.length - raw.trimStart().length));
      const rect = range.getBoundingClientRect();
      setManualSelection({ content: canonicalContent, viewMode, sourceAnchor: "markdown-document",
        startOffset, endOffset: startOffset + codePointLength(canonicalContent), offsetScope: "canonical_markdown",
        top: Math.max(72, rect.top - 48), left: Math.min(window.innerWidth - 180, Math.max(16, rect.left)) });
      setManualChunkError(false);
      setSourceLocationError(false);
      return;
    }
    const node = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE ? range.commonAncestorContainer as Element : range.commonAncestorContainer.parentElement;
    const anchorElement = node?.closest<HTMLElement>("[data-source-anchor]");
    const sourceAnchor = viewMode === "markdown" ? "markdown-document" : anchorElement?.dataset.sourceAnchor || "original-document";
    const canonicalRoot = viewer.querySelector<HTMLElement>("[data-canonical-markdown-source] code");
    const offsetRoot = viewMode === "markdown" ? canonicalRoot : anchorElement ?? viewer;
    if (!offsetRoot) return;
    if (!offsetRoot.contains(range.startContainer) || !offsetRoot.contains(range.endContainer)) return;
    const preRange = document.createRange();
    preRange.selectNodeContents(offsetRoot);
    preRange.setEnd(range.startContainer, range.startOffset);
    const leadingWhitespace = rawSelection.slice(0, rawSelection.length - rawSelection.trimStart().length);
    const startOffset = codePointLength(preRange.toString()) + codePointLength(leadingWhitespace);
    const endOffset = startOffset + codePointLength(content);
    const rect = range.getBoundingClientRect();
    setManualSelection({
      content,
      viewMode,
      sourceAnchor,
      startOffset,
      endOffset,
      offsetScope: viewMode === "markdown" ? "canonical_markdown" : "source_anchor",
      top: Math.max(72, rect.top - 48),
      left: Math.min(window.innerWidth - 180, Math.max(16, rect.left + rect.width / 2 - 70))
    });
    setManualChunkError(false);
  }

  async function submitManualChunk() {
    if (!manualSelection || !liveDetail?.manual_edit_enabled) return;
    setManualChunkBusy(true);
    setManualChunkError(false);
    try {
      const refreshed = await createManualChunk(apiFetch, params.id, liveDetail.document.id, liveDetail.version.id, {
        content: manualSelection.content,
        view_mode: manualSelection.viewMode,
        source_anchor: manualSelection.sourceAnchor,
        start_offset: manualSelection.startOffset,
        end_offset: manualSelection.endOffset,
        offset_unit: "unicode_code_point",
        offset_scope: manualSelection.offsetScope,
        lock_version: liveDetail.version.lock_version
      });
      setLiveDetail(refreshed);
      const selectedId = refreshed.chunks.find((chunk) => chunk.content === manualSelection.content)?.id ?? refreshed.chunks[0]?.id;
      setSelectedChunkIds(selectedId ? [selectedId] : []);
      setManualSelection(null);
      window.getSelection()?.removeAllRanges();
    } catch {
      setManualChunkError(true);
    } finally {
      setManualChunkBusy(false);
    }
  }

  return { manualSelection, setManualSelection, manualChunkBusy, manualChunkError, captureManualSelection, submitManualChunk };
}
