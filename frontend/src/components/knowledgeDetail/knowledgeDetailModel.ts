"use client";

import { ocrFailureKey, ocrRetryBlocked } from "@/lib/ocrPresentation";
import { completionGateBlocksKnowledgeDetail } from "@/lib/knowledgeReadiness";
import { type ApprovalChunkEvidence, type KnowledgeDetailResponse, type KnowledgeTagResponse, type PipelineRunDetail } from "@/lib/api";
import { type TranslationKey } from "@/lib/i18nClient";
import { resolvedSourceMappings, type ResolvedSourceMapping } from "@/lib/markdownSourceMapping";

/* Knowledge detail page types and helpers (split from the page, OPT424-038). */

export type Translate = (key: TranslationKey) => string;

export type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

export type KnowledgeChunk = {
  id: string;
  index: number;
  title: string;
  type: "text" | "image" | "table" | "chart";
  sourceAnchor: string;
  sourceMappings: ResolvedSourceMapping[];
  sourceLabel: string;
  content: string;
  displayMarkdown: string | null;
  markdownContent: string | null;
  tokens: number;
  confidence: number;
  tags: string[];
  tagDetails: KnowledgeTagResponse[];
};

export type ArticleView = "original" | "markdown";

export type DocumentView = ArticleView | "tags";

export type ManualTextSelection = {
  content: string;
  viewMode: ArticleView;
  sourceAnchor: string;
  startOffset: number;
  endOffset: number;
  offsetScope: "canonical_markdown" | "source_anchor";
  top: number;
  left: number;
};

export function sourceAnchor(chunk: ApprovalChunkEvidence) {
  const resolved = resolvedSourceMappings(chunk.source_mapping)[0];
  if (resolved) return resolved.sourceAnchor;
  const firstMapping = chunk.source_mapping[0] as Record<string, unknown> | undefined;
  const mappedAnchor = firstMapping?.sourceAnchor ?? firstMapping?.source_anchor ?? firstMapping?.anchor;
  return typeof mappedAnchor === "string" && mappedAnchor ? mappedAnchor : `chunk-${chunk.chunk_index}`;
}

export function sourceLabel(chunk: ApprovalChunkEvidence, _t: Translate, format: Format) {
  const firstMapping = chunk.source_mapping[0] as Record<string, unknown> | undefined;
  const page = firstMapping?.page ?? firstMapping?.page_number;
  if (typeof page === "number" || typeof page === "string") return format("knowledgeDetailOriginalPage", { page });
  return format("knowledgeDetailChunkLabel", { number: chunk.chunk_index });
}

export function chunkType(contentType: string): KnowledgeChunk["type"] {
  if (contentType === "image" || contentType === "table" || contentType === "chart") return contentType;
  return "text";
}

export function displayChunkTitle(title: string | null | undefined, chunkIndex: number, format: Format) {
  const fallback = format("knowledgeDetailChunkTitle", { number: chunkIndex });
  const candidate = title?.trim() || fallback;
  return candidate.replace(new RegExp(`\\s+#${chunkIndex}\\s*$`), "").trim() || fallback;
}

export function visibleTagDetails(tags: KnowledgeTagResponse[]) {
  return tags.filter((tag) => tag.source !== "rule");
}

export function liveChunk(chunk: ApprovalChunkEvidence, t: Translate, format: Format): KnowledgeChunk {
  const tagDetails = chunk.tag_details ?? chunk.tags.map((tag, index) => ({ tag_id: `${chunk.id}-${index}`, tag_text: tag, source: "legacy", confidence_score: null, metadata: {}, created_by: null, created_at: "" }));
  return {
    id: chunk.id,
    index: chunk.chunk_index,
    title: displayChunkTitle(chunk.title, chunk.chunk_index, format),
    type: chunkType(chunk.content_type),
    sourceAnchor: sourceAnchor(chunk),
    sourceMappings: resolvedSourceMappings(chunk.source_mapping),
    sourceLabel: sourceLabel(chunk, t, format),
    content: chunk.content,
    displayMarkdown: chunk.display_markdown,
    markdownContent: chunk.markdown_content,
    tokens: chunk.token_count ?? 0,
    confidence: chunk.confidence_score ?? 0,
    tags: visibleTagDetails(tagDetails).map((tag) => tag.tag_text),
    tagDetails: visibleTagDetails(tagDetails)
  };
}

export function layoutUnavailableLabel(status: string | undefined, t: Translate) {
  if (status === "partial") return t("knowledgeDetailLayoutPartial");
  if (status === "failed") return t("knowledgeDetailLayoutFailed");
  return t("knowledgeDetailLayoutUnavailable");
}

export function isPipelineActive(pipeline: PipelineRunDetail | null | undefined) {
  return Boolean(pipeline && ["running", "processing", "waiting_action", "queued"].includes(pipeline.status));
}

export function failedPipelineStep(pipeline: PipelineRunDetail | null | undefined) {
  return pipeline?.steps.find((step) => step.status === "failed") ?? null;
}

export function shouldPollKnowledgeCompletionGate(detail: KnowledgeDetailResponse | null) {
  const pipeline = detail?.pipeline;
  if (!pipeline || !completionGateBlocksKnowledgeDetail(detail)) return false;
  if (pipeline.status === "failed" || failedPipelineStep(pipeline)) return false;
  return isPipelineActive(pipeline);
}

export function pipelineFailureKey(step: PipelineRunDetail["steps"][number] | null | undefined, message?: string | null): TranslationKey {
  return ocrFailureKey(step, message);
}

export function imageOcrRetryBlocked(step: PipelineRunDetail["steps"][number] | null | undefined) {
  return ocrRetryBlocked(step);
}
