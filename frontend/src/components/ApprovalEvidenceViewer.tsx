"use client";

import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Code2, FileText } from "lucide-react";
import { CanonicalMarkdownSource } from "@/components/CanonicalMarkdownSource";
import { ChunkMarkdownView } from "@/components/ChunkMarkdownView";
import { DocumentLayoutViewer } from "@/components/DocumentLayoutViewer";
import { SafeMarkdown } from "@/components/SafeMarkdown";
import { toggleSingleChunkSelection } from "@/lib/evidenceSelection";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { chunkIdsForResolvedSourceAnchor, markdownArtifactReasonKey, sourceAnchorsForChunks, sourceSelectionGroupsForChunks, sourceSelectionScrollBehavior, type ResolvedSourceMapping } from "@/lib/markdownSourceMapping";
import type { DocumentLayoutPage, KnowledgeTagResponse, OriginalFileViewerMetadata } from "@/lib/api";

export type EvidenceChunk = {
  id: string;
  index?: number;
  type: "text" | "image" | "table" | "chart";
  title?: string;
  sourceAnchor?: string;
  sourceMappings?: ResolvedSourceMapping[];
  sourceLabel: string;
  content: string;
  displayMarkdown?: string | null;
  markdownContent?: string | null;
  tokens?: number;
  confidence?: number;
  tags: string[];
  tagDetails?: KnowledgeTagResponse[];
};

type EvidenceDocumentLayout = {
  status: "available" | "partial" | "missing" | "failed";
  reason_code: string | null;
  source: string | null;
  pages: DocumentLayoutPage[];
};

function chunkTypeClass(type: EvidenceChunk["type"]) {
  return type === "text" ? "" : ` chunk-type-${type}`;
}

function visibleTags(chunk: EvidenceChunk): KnowledgeTagResponse[] {
  if (chunk.tagDetails?.length) return chunk.tagDetails.filter((tag) => tag.source !== "rule");
  return chunk.tags.map((tag, index) => ({
    tag_id: `${chunk.id}-${index}`,
    tag_text: tag,
    source: "legacy",
    confidence_score: null,
    metadata: {},
    created_by: null,
    created_at: ""
  }));
}

function isMarkdownOriginal(metadata: OriginalFileViewerMetadata | null | undefined) {
  return metadata?.viewer_type === "markdown" && metadata.markdown_source_mode === "rendered_original_raw_markdown";
}

function layoutStatusLabel(status: EvidenceDocumentLayout["status"] | undefined, t: (key: TranslationKey) => string) {
  if (status === "partial") return t("knowledgeDetailLayoutPartial");
  if (status === "failed") return t("knowledgeDetailLayoutFailed");
  return t("knowledgeDetailLayoutUnavailable");
}

export function ApprovalEvidenceViewer({
  documentTitle,
  version,
  chunks,
  originalFile,
  documentLayout,
  sourceText,
  markdownText,
  markdownArtifactReasonCode,
  documentTags = []
}: {
  documentTitle: string;
  version: string;
  chunks: EvidenceChunk[];
  originalFile?: OriginalFileViewerMetadata | null;
  documentLayout?: EvidenceDocumentLayout | null;
  sourceText?: string | null;
  markdownText?: string | null;
  markdownArtifactReasonCode?: string | null;
  documentTags?: KnowledgeTagResponse[];
}) {
  const { t, format } = useI18n();
  const [view, setView] = useState<"original" | "markdown">("original");
  const [selectedChunkIds, setSelectedChunkIds] = useState<string[]>([]);
  const [sourceScrollSequence, setSourceScrollSequence] = useState(0);
  const [chunkScrollRequest, setChunkScrollRequest] = useState<{ chunkId: string; sequence: number } | null>(null);
  const [sourceLocationError, setSourceLocationError] = useState(false);
  const articleViewerRef = useRef<HTMLDivElement>(null);
  const chunkListRef = useRef<HTMLDivElement>(null);
  const skipNextSourceScrollRef = useRef(false);
  const displayChunks = useMemo(() => chunks.map((chunk, index) => ({ ...chunk, sourceAnchor: chunk.sourceAnchor || `approval-live-chunk-${index}`, sourceMappings: chunk.sourceMappings ?? [] })), [chunks]);
  const selectedChunks = useMemo(() => displayChunks.filter((chunk) => selectedChunkIds.includes(chunk.id)), [displayChunks, selectedChunkIds]);
  const selectedSourceAnchors = useMemo(() => sourceAnchorsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);
  const selectedSourceGroups = useMemo(() => sourceSelectionGroupsForChunks(displayChunks, selectedChunkIds), [displayChunks, selectedChunkIds]);

  useEffect(() => {
    const firstSelected = selectedChunks[0];
    if (!firstSelected) return;
    if (skipNextSourceScrollRef.current) {
      skipNextSourceScrollRef.current = false;
      return;
    }
    const animationFrame = requestAnimationFrame(() => {
      const viewer = articleViewerRef.current;
      const target = view === "markdown"
        ? viewer?.querySelector<HTMLElement>(`[data-chunk-ids~="${CSS.escape(firstSelected.id)}"]`)
        : viewer?.querySelector<HTMLElement>(`[data-source-anchor="${CSS.escape(firstSelected.sourceAnchor)}"]`);
      if (!viewer || !target) {
        setSourceLocationError(true);
        return;
      }
      const viewerRect = viewer.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const top = viewer.scrollTop + targetRect.top - viewerRect.top - (viewer.clientHeight - targetRect.height) / 2;
      setSourceLocationError(false);
      viewer.scrollTo({ behavior: sourceSelectionScrollBehavior(), top: Math.max(0, top) });
    });
    return () => cancelAnimationFrame(animationFrame);
  }, [view, sourceScrollSequence, selectedChunks]);

  useEffect(() => {
    if (!chunkScrollRequest) return;
    const animationFrame = requestAnimationFrame(() => {
      const list = chunkListRef.current;
      const target = list?.querySelector<HTMLElement>(`[data-chunk-id="${chunkScrollRequest.chunkId}"]`);
      if (!list || !target) return;
      const listRect = list.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const top = list.scrollTop + targetRect.top - listRect.top - (list.clientHeight - targetRect.height) / 2;
      list.scrollTo({ behavior: sourceSelectionScrollBehavior(), top: Math.max(0, top) });
    });
    return () => cancelAnimationFrame(animationFrame);
  }, [chunkScrollRequest]);

  function selectChunk(chunkId: string) {
    const nextSelection = toggleSingleChunkSelection(selectedChunkIds, chunkId);
    setSelectedChunkIds(nextSelection);
    if (!nextSelection.length) {
      setSourceLocationError(false);
      return;
    }
    setSourceScrollSequence((sequence) => sequence + 1);
  }

  function selectSourceAnchor(sourceAnchor: string) {
    const matchingIds = chunkIdsForResolvedSourceAnchor(displayChunks, sourceAnchor);
    if (!matchingIds.length) {
      setSourceLocationError(true);
      return;
    }
    skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(matchingIds);
    setSourceLocationError(false);
    setChunkScrollRequest((request) => ({ chunkId: matchingIds[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  function selectMarkdownChunks(chunkIds: string[]) {
    if (!chunkIds.length) return;
    skipNextSourceScrollRef.current = true;
    setSelectedChunkIds(chunkIds);
    setSourceLocationError(false);
    setChunkScrollRequest((request) => ({ chunkId: chunkIds[0], sequence: (request?.sequence ?? 0) + 1 }));
  }

  function handleSourceKeyDown(event: KeyboardEvent<HTMLElement>, sourceAnchor: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectSourceAnchor(sourceAnchor);
    }
  }

  return (
    <div className="approval-evidence-viewer">
      <div className="approval-evidence-toolbar">
        <div><strong>{documentTitle}</strong><small>{version} · {t("approvalEvidenceReadonly")}</small></div>
      </div>
      <div className="approval-evidence-columns">
        <section aria-label={t("approvalEvidenceSourceAria")} className="approval-document-pane">
          <div className="approval-document-header">
            <strong>{t("approvalEvidenceArticle")}</strong>
            <div className="document-view-toggle" aria-label={t("approvalEvidenceViewMode")} role="group">
              <button aria-pressed={view === "original"} className={view === "original" ? "active" : ""} onClick={() => setView("original")} type="button"><FileText size={15} /> {t("originalDocument")}</button>
              <button aria-pressed={view === "markdown"} className={view === "markdown" ? "active" : ""} onClick={() => setView("markdown")} type="button"><Code2 size={15} /> {t("markdownView")}</button>
            </div>
          </div>
          <div className={`article-viewer article-viewer-${view} approval-article-viewer`} ref={articleViewerRef}>
            {view === "original" ? (
              <article className="document-article">
                {isMarkdownOriginal(originalFile) ? (
                  <section className="document-page markdown-original-page">
                    <div className="document-page-content">
                      {sourceText ? <SafeMarkdown className="rendered-markdown-document" source={sourceText} /> : <div className="empty-state compact">{t("approvalEvidenceNoLiveOriginal")}</div>}
                    </div>
                    <footer className="document-page-number">MD</footer>
                  </section>
                ) : null}
                {!isMarkdownOriginal(originalFile) && documentLayout?.pages.length ? (
                  <DocumentLayoutViewer formatPageLabel={(page) => format("knowledgeDetailOriginalPage", { page })} onKeyDown={handleSourceKeyDown} onSelect={selectSourceAnchor} pages={documentLayout.pages} selectedAnchors={selectedSourceAnchors} selectionGroups={selectedSourceGroups} />
                ) : null}
                {!isMarkdownOriginal(originalFile) && !documentLayout?.pages.length ? (
                  <section className="document-page">
                    <div className="document-page-content">
                      <div className="empty-state compact">
                        <strong>{layoutStatusLabel(documentLayout?.status, t)}</strong>
                        {documentLayout?.reason_code ? <small>{documentLayout.reason_code}</small> : <span>{t("approvalEvidenceNoLiveOriginal")}</span>}
                      </div>
                    </div>
                    <footer className="document-page-number">-</footer>
                  </section>
                ) : null}
              </article>
            ) : (
              <div className="article-markdown">
                {!markdownText ? <div className="empty-state compact">{t(markdownArtifactReasonKey(markdownArtifactReasonCode))}</div> : null}
                {markdownText ? <CanonicalMarkdownSource chunks={displayChunks} onSelectChunkIds={selectMarkdownChunks} selectedChunkIds={selectedChunkIds} source={markdownText} /> : null}
              </div>
            )}
          </div>
          <div className="tag-result-strip document-tag-result-strip">
            <span className="tag-result-strip-label">{t("knowledgeDetailDocumentTags")}</span>
            <div className="tag-result-strip-list">
              {documentTags.length ? documentTags.map((tag) => (
                <span className={`knowledge-tag-chip tag-source-${tag.source}`} key={tag.tag_id}>
                  <em>{tag.tag_text}</em>
                  <small>{tag.source}</small>
                </span>
              )) : <small>{t("knowledgeDetailNoTags")}</small>}
            </div>
          </div>
          {sourceLocationError ? <div className="source-location-error">{t("sourceLocationError")}</div> : null}
        </section>
        <section aria-label={t("approvalEvidenceChunksAria")}>
          <div className="approval-chunk-list-header"><strong>{t("approvalEvidenceChunkResults")}</strong><span>{format("approvalEvidenceChunkListHelp", { count: displayChunks.length })}</span></div>
          <div className="chunk-list extraction-chunks approval-evidence-chunks" ref={chunkListRef}>
            {displayChunks.map((chunk) => {
              const tags = visibleTags(chunk);
              return (
                <article
                  aria-label={format("knowledgeDetailSelectChunkAria", { id: chunk.id, number: chunk.index ?? 0 })}
                  aria-pressed={selectedChunkIds.includes(chunk.id)}
                  className={selectedChunkIds.includes(chunk.id) ? "chunk-card selected" : "chunk-card"}
                  data-chunk-id={chunk.id}
                  key={chunk.id}
                  onClick={() => selectChunk(chunk.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      selectChunk(chunk.id);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                >
                  <div className="chunk-head">
                    <span className="chunk-title-row">
                      <span className="chunk-title-meta">
                        <span className="chunk-index-badge">#{chunk.index ?? "?"}</span>
                        <small className="chunk-inline-meta">
                          <span>{chunk.sourceLabel}</span>
                          <span>{format("knowledgeDetailTokenCount", { count: chunk.tokens ?? 0 })}</span>
                          <span>{format("knowledgeDetailConfidence", { value: Math.round((chunk.confidence ?? 0) * 100) })}</span>
                        </small>
                      </span>
                      <small className="chunk-technical-id">{chunk.id}</small>
                    </span>
                  </div>
                  <div className="chunk-content-shell">
                    <ChunkMarkdownView
                      chunk={{
                        content: chunk.content,
                        display_markdown: chunk.displayMarkdown,
                        markdown_content: chunk.markdownContent,
                      }}
                      className="chunk-safe-markdown"
                    />
                    {chunk.type !== "text" ? <span className={`chunk-type${chunkTypeClass(chunk.type)}`}>{chunk.type}</span> : null}
                  </div>
                  <div className="knowledge-tag-editor readonly">
                    <span className="knowledge-tag-editor-label">{t("knowledgeDetailChunkTagResults")}</span>
                    <div className="knowledge-tag-list">
                      {tags.length ? tags.map((tag) => (
                        <span className={`knowledge-tag-chip tag-source-${tag.source}`} key={tag.tag_id}>
                          <em>{tag.tag_text}</em>
                          <small>{tag.source}</small>
                        </span>
                      )) : <small>{t("knowledgeDetailNoTags")}</small>}
                    </div>
                  </div>
                </article>
              );
            })}
            {!displayChunks.length ? <div className="empty-state compact">{t("approvalEvidenceNoLiveChunks")}</div> : null}
          </div>
        </section>
      </div>
    </div>
  );
}
