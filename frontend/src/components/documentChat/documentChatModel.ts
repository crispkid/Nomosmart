// Document chat test model: types and pure helpers (split from the chat-test page, OPT424-038).
import { UiValidationError } from "@/lib/transportError";
import { type ValidationRunResponse, type ProjectChatCitation } from "@/lib/api";
import { type TranslationKey } from "@/lib/i18nClient";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";

export type Judgment = "correct" | "needs_revision";
export type AnswerEvaluation = { judgment: Judgment; suggestion: string };
export type Translate = (key: TranslationKey) => string;
export type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
export type ConversationEntry = {
  id: string;
  recordId?: string;
  validationStatus?: string;
  question: string;
  answer?: string;
  askedAt: string;
  answeredAt?: string | null;
  citations: ProjectChatCitation[];
  loading?: boolean;
  error?: string;
  status?: "answered" | "no_answer";
};

export function validationEntries(run: ValidationRunResponse, t: Translate, format: Format): ConversationEntry[] {
  const running = ["queued", "running"].includes(run.status);
  return run.items.map((item, index) => ({
    id: item.id,
    recordId: item.chat_record_id ?? undefined,
    validationStatus: item.status,
    question: item.question,
    answer: item.answer ?? undefined,
    askedAt: new Date(Date.parse(run.created_at) + index).toISOString(),
    answeredAt: item.answer ? run.completed_at : null,
    citations: item.citations,
    loading: running && ["pending", "running"].includes(item.status),
    error: item.status === "error" ? operationalCodeMessage(item.error_code, t, format, "documentChatQueryFailed") : undefined,
    status: item.answer ? "answered" : undefined
  }));
}

export function parseCsv(text: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (inQuotes) {
      if (character === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') inQuotes = false;
      else cell += character;
      continue;
    }
    if (character === '"') inQuotes = true;
    else if (character === ",") {
      row.push(cell);
      cell = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else cell += character;
  }
  if (inQuotes) throw new UiValidationError("projectChatCsvUnclosedQuote");
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

export function downloadTextFile(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function retrievalErrorMessage(error: unknown, t: Translate, format: Format) {
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code?: unknown }).code) : "";
  if (code === "embedding_provider_required" || code === "embedding_model_required" || code === "embedding_adapter_credential_required" || code === "embedding_adapter_secret_ref_unresolved") return t("projectChatEmbeddingProviderRequired");
  if (code === "query_embedding_failed" || code === "embedding_adapter_unavailable" || code === "embedding_adapter_provider_rejected" || code === "embedding_response_invalid") return t("projectChatQueryEmbeddingFailed");
  if (code === "vector_index_not_ready" || code === "embedding_profile_required") return t("projectChatVectorIndexNotReady");
  if (code === "embedding_profile_mismatch") return t("projectChatEmbeddingProfileMismatch");
  if (code === "hybrid_retrieval_failed" || code === "opensearch_retrieval_unavailable") return t("projectChatOpenSearchUnavailable");
  if (code === "retrieval_scope_inconsistent") return t("projectChatRetrievalScopeInconsistent");
  if (code === "provider_response_contract_invalid") return t("chatCitationProviderMismatch");
  return operationalErrorMessage(error, t, format, "documentChatQueryFailed");
}
