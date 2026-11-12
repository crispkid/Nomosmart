import type { TranslationKey } from "@/lib/i18nClient";

/** One label table for every document pipeline step (OPT424-034). */
const PIPELINE_STEP_LABELS: Record<string, TranslationKey> = {
  upload_received: "knowledgeDetailStepUploadReceived",
  file_scan: "knowledgeDetailStepFileScan",
  parse_document: "knowledgeDetailStepParseDocument",
  ocr_extract: "knowledgeDetailStepOcrExtract",
  split_paragraphs: "knowledgeDetailStepSplitParagraphs",
  parse_structure: "knowledgeDetailStepChunkKnowledge",
  chunk_knowledge: "knowledgeDetailStepChunkKnowledge",
  generate_markdown: "knowledgeDetailStepGenerateMarkdown",
  auto_tag: "knowledgeDetailStepAutoTag",
  embedding: "knowledgeDetailStepBuildEmbeddings",
  build_embeddings: "knowledgeDetailStepBuildEmbeddings",
  staging_index: "knowledgeDetailStepBuildStagingIndex",
  build_staging_index: "knowledgeDetailStepBuildStagingIndex",
  build_graph_preview: "knowledgeDetailStepBuildGraphPreview",
  cleanup_superseded: "pipelineStepCleanupSuperseded",
  prepare_submission: "knowledgeDetailStepPrepareSubmission",
  manager_review: "knowledgeDetailStepManagerReview",
  owner_review: "knowledgeDetailStepOwnerReview",
  publish: "knowledgeDetailStepPublish",
  production_index: "knowledgeDetailStepProductionIndex",
  graph_sync: "knowledgeDetailStepGraphSync",
};

export function pipelineStepLabel(stepName: string | null | undefined, t: (key: TranslationKey) => string): string {
  if (!stepName) return t("knowledgeDetailPipelineStepUnknown");
  const key = PIPELINE_STEP_LABELS[stepName];
  return key ? t(key) : stepName.replaceAll("_", " ");
}

export const knownPipelineSteps = Object.keys(PIPELINE_STEP_LABELS);
