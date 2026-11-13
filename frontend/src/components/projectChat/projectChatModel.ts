// Project chat test model: types and pure helpers (split from ProjectChatTest, OPT424-038).
import { UiValidationError } from "@/lib/transportError";
import { type ProjectChatCitation, type ProjectChatConversationResponse } from "@/lib/api";
import { type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

export type ChatDocument = { id: string; documentId: string; title: string; version: string; source: string; chunks: number; documentStatus: string; versionStatus: string };
export type Entry = { id: number; recordId?: string; validationItemId?: string; question: string; answer?: string; citations?: ProjectChatCitation[]; loading?: boolean; error?: string; status?: "answered" | "no_answer"; retrievalStrategy?: string };
export type Judgment = "correct" | "revision";
export type CsvValidationQuestion = {
  question: string;
  expected_answer?: string | null;
  expected_keywords?: string[];
  selected_document_ids?: string[];
  category?: string | null;
  priority?: string | null;
};
export type ProjectConversation = {
  id: string;
  scopeIds: string[];
  entries: Entry[];
  judgments: Record<number, Judgment>;
  createdAt: number;
  updatedAt: number;
  persisted?: boolean;
  history?: ProjectChatConversationResponse;
  validationRunId?: string;
};

export type Translate = (key: TranslationKey) => string;
export type Format = (key: TranslationKey, values: Record<string, string | number>) => string;

export function parseCsv(text: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { cell += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else cell += character;
    } else if (character === '"') quoted = true;
    else if (character === ",") { row.push(cell); cell = ""; }
    else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = []; cell = "";
    } else cell += character;
  }
  if (quoted) throw new UiValidationError("projectChatCsvUnclosedQuote");
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

export function downloadCsv(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function retrievalErrorMessage(error: unknown, t: Translate, format: Format) {
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code?: unknown }).code) : "";
  if (code === "active_manifest_required") return t("projectChatActiveManifestRequired");
  if (code === "retrieval_scope_denied") return t("projectChatRetrievalScopeDenied");
  if (code === "published_index_not_ready") return t("projectChatPublishedIndexNotReady");
  if (code === "opensearch_retrieval_unavailable" || code === "hybrid_retrieval_failed") return t("projectChatOpenSearchUnavailable");
  if (code === "retrieval_scope_inconsistent") return t("projectChatRetrievalScopeInconsistent");
  if (code === "embedding_provider_required" || code === "embedding_model_required" || code === "embedding_adapter_credential_required" || code === "embedding_adapter_secret_ref_unresolved") return t("projectChatEmbeddingProviderRequired");
  if (code === "query_embedding_failed" || code === "embedding_adapter_unavailable" || code === "embedding_adapter_provider_rejected" || code === "embedding_response_invalid") return t("projectChatQueryEmbeddingFailed");
  if (code === "vector_index_not_ready" || code === "embedding_profile_required") return t("projectChatVectorIndexNotReady");
  if (code === "embedding_profile_mismatch") return t("projectChatEmbeddingProfileMismatch");
  if (code === "citation_scope_mismatch") return t("projectChatCitationScopeMismatch");
  if (code === "provider_response_contract_invalid") return t("chatCitationProviderMismatch");
  return operationalErrorMessage(error, t, format, "projectChatRetrievalFailed");
}

export function retrievalLabel(strategy?: string) {
  if (strategy === "hybrid") return "Hybrid Retrieval";
  if (strategy === "vector") return "Vector Retrieval";
  if (strategy === "keyword") return "Keyword Retrieval";
  return "Live RAG";
}

export function newConversationId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `conversation-${Date.now()}`;
}

export function isUuid(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export function sameScopeIds(left: string[], right: string[]) {
  return left.length === right.length && left.slice().sort().join() === right.slice().sort().join();
}

export function timestamp(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : Date.now();
}

export function conversationFromHistory(item: ProjectChatConversationResponse): ProjectConversation {
  const entries = item.records.map((record, index) => ({
    id: index,
    recordId: record.id,
    question: record.question,
    answer: record.answer ?? undefined,
    citations: record.citations,
    status: record.answer ? "answered" as const : "no_answer" as const
  }));
  const judgmentEntries = item.records.flatMap((record, index): [number, Judgment][] => {
    if (record.evaluation === "needs_revision") return [[index, "revision"]];
    if (record.evaluation === "correct") return [[index, "correct"]];
    return [];
  });
  const updatedAt = timestamp(item.updated_at);
  return {
    id: item.id,
    scopeIds: item.selected_document_version_ids,
    entries,
    judgments: Object.fromEntries(judgmentEntries) as Record<number, Judgment>,
    createdAt: updatedAt,
    updatedAt,
    persisted: true,
    history: item,
  };
}

export function validationItemMessage(status: string, answer: string | null | undefined, t: Translate) {
  if (answer) return answer;
  if (status === "running") return t("projectChatValidationRunning");
  if (status === "error") return t("projectChatValidationFailed");
  if (status === "failed") return t("projectChatValidationFailedScore");
  if (status === "needs_review") return t("projectChatValidationNeedsReview");
  if (status === "completed" || status === "passed") return t("projectChatValidationCompletedNoAnswer");
  return t("projectChatValidationQueued");
}

/** Parses an uploaded validation CSV into questions; throws a translated validation error for invalid files. */
export function parseValidationQuestionsCsv(contents: string, scopeIds: string[], format: Format): CsvValidationQuestion[] {
  const rows = parseCsv(contents);
  const headers = rows[0]?.map((value, index) => (index ? value : value.replace(/^\uFEFF/, "")).trim()) ?? [];
  const questionIndex = headers.indexOf("question");
  if (questionIndex < 0) throw new UiValidationError("projectChatCsvMissingQuestion");
  const expectedAnswerIndex = headers.indexOf("expected_answer");
  const expectedKeywordsIndex = headers.indexOf("expected_keywords");
  const selectedDocumentsIndex = headers.indexOf("selected_document_ids");
  const categoryIndex = headers.indexOf("category");
  const priorityIndex = headers.indexOf("priority");
  const splitList = (value: string | undefined) => (value ?? "").split(/[;,|]/).map((id) => id.trim()).filter(Boolean);
  const valueAt = (row: string[], index: number) => index >= 0 ? (row[index] ?? "").trim() : "";
  const questions = rows.slice(1).map((row): CsvValidationQuestion | null => {
    const questionText = valueAt(row, questionIndex);
    if (!questionText) return null;
    return {
      question: questionText,
      expected_answer: valueAt(row, expectedAnswerIndex) || null,
      expected_keywords: splitList(valueAt(row, expectedKeywordsIndex)),
      selected_document_ids: splitList(valueAt(row, selectedDocumentsIndex)),
      category: valueAt(row, categoryIndex) || null,
      priority: valueAt(row, priorityIndex) || null
    };
  }).filter((item): item is CsvValidationQuestion => item !== null);
  const invalidIds = questions.flatMap((question) => question.selected_document_ids ?? []).filter((id) => !scopeIds.includes(id));
  if (invalidIds.length) throw new Error(format("projectChatCsvInvalidScope", { ids: [...new Set(invalidIds)].join(", ") }));
  if (!questions.length) throw new UiValidationError("projectChatCsvNoQuestions");
  return questions;
}
