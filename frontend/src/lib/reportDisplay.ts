import type { TranslationKey } from "@/lib/i18n";

type Translate = (key: TranslationKey) => string;

const labelGroups = {
  scope: {
    owner_projects: "reportScopeOwnerProjects",
    accessible: "reportScopeAccessible",
    reviewer: "reportScopeReviewer",
    system: "reportScopeSystem"
  },
  metric_key: {
    document_count: "reportMetricDocuments",
    active_documents: "reportColActiveDocuments",
    deleted_documents: "reportMetricDeletedDocuments",
    chat_count: "reportColQaCount",
    no_answer_rate: "reportColNoAnswerRate",
    cited_answer_rate: "reportColCitedAnswerRate",
    validation_run_count: "reportMetricValidationRuns",
    validation_pass_rate: "reportMetricValidationPassRate"
  },
  usage_purpose: {
    chat_test: "reportPurposeChatTest",
    public_api_chat: "reportPurposePublicApiChat",
    validation_answer: "reportPurposeValidationAnswer",
    validation_judge: "reportPurposeValidationJudge",
    document_auto_tag: "reportPurposeDocumentAutoTag",
    chunk_auto_tag: "reportPurposeChunkAutoTag",
    pipeline_auto_tag: "reportPurposePipelineAutoTag",
    ocr_extract: "reportPurposeOcrExtract",
    embedding_build: "reportPurposeEmbeddingBuild",
    query_embedding: "reportPurposeQueryEmbedding",
    connection_test: "reportPurposeConnectionTest"
  },
  source_channel: {
    chat_test: "reportSourceChatTest",
    public_api: "reportSourcePublicApi",
    validation: "reportSourceValidation",
    pipeline: "reportSourcePipeline",
    knowledge_detail: "reportSourceKnowledgeDetail",
    system_management: "reportSourceSystemManagement"
  }
} satisfies Record<string, Record<string, TranslationKey>>;

type LabelField = keyof typeof labelGroups;
const unknownLabels: Record<LabelField, TranslationKey> = {
  scope: "reportUnknownScope",
  metric_key: "reportUnknownMetric",
  usage_purpose: "reportUnknownPurpose",
  source_channel: "reportUnknownSource"
};

export const reportUsagePurposes = Object.keys(labelGroups.usage_purpose);
export const reportSourceChannels = Object.keys(labelGroups.source_channel);

/** Display only: API and CSV values must never pass through this mapping. */
export function reportDisplayValue(field: string, value: unknown, t: Translate) {
  if (!Object.hasOwn(labelGroups, field) || typeof value !== "string" || !value) return null;
  const name = field as LabelField;
  const labels: Record<string, TranslationKey> = labelGroups[name];
  return Object.hasOwn(labels, value)
    ? { label: t(labels[value]), code: null }
    : { label: t(unknownLabels[name]), code: value };
}

export function reportProjectLabel(
  project: string,
  options: { projects: ReadonlyArray<{ id: string; name: string }> } | null,
  t: Translate,
) {
  if (project === "all") return t("reportAllProjects");
  return options?.projects.find((item) => item.id === project)?.name || t("reportProjectUnavailable");
}
