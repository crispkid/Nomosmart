import type { ApiError } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18n";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

const codeTranslationKeys: Partial<Record<string, TranslationKey>> = {
  upload_request_too_large: "uploadRequestTooLarge",
  upload_capacity_exhausted: "uploadCapacityExhausted",
  upload_receive_timeout: "uploadReceiveTimeout",
  upload_temporary_storage_unavailable: "uploadTemporaryStorageUnavailable",
  chunk_artifacts_not_ready: "projectChatVectorIndexNotReady",
  published_index_evidence_invalid: "publishedIndexEvidenceInvalid",
  chunk_delete_reference_conflict: "knowledgeDetailDeleteChunkReferenceConflict",
  conversation_read_only: "chatConversationWriteDenied",
  conversation_busy: "chatConversationBusy",
  conversation_identity_conflict: "chatConversationIdentityConflict",
  conversation_not_found: "apiNotFound",
  conversation_scope_locked: "projectChatScopeChangedWarning",
  project_editor_archive_forbidden: "chatEditorArchiveDenied",
  application_access_denied: "applicationAccessDeniedDescription",
  archive_confirmation_required: "apiConflict",
  authentication_required: "apiUnauthorized",
  invalid_project_model: "projectsModelConfigurationRequired",
  model_credential_required: "apiConfigurationRequired",
  permission_denied: "apiForbidden",
  project_archived: "apiConflict",
  project_model_configuration_required: "projectsModelConfigurationRequired",
  project_model_pair_required: "projectsModelPairRequired",
  project_name_required: "projectsNameRequired",
  project_not_found: "apiNotFound",
  project_owner_required: "apiForbidden",
  stale_project_version: "apiConflict",
  validation_error: "apiValidation",
};

function asApiError(error: unknown): ApiError | null {
  if (!(error instanceof Error)) return null;
  const candidate = error as Partial<ApiError>;
  return typeof candidate.status === "number" && typeof candidate.code === "string" ? error as ApiError : null;
}

function statusTranslationKey(status: number): TranslationKey {
  if (status === 401) return "apiUnauthorized";
  if (status === 403) return "apiForbidden";
  if (status === 404) return "apiNotFound";
  if (status === 409) return "apiConflict";
  if (status === 422) return "apiValidation";
  if (status >= 500) return "apiServiceUnavailable";
  return "apiGenericError";
}

function withRequestId(message: string, requestId: string | undefined, format: Format): string {
  return requestId ? format("apiErrorWithRequestId", { message, requestId }) : message;
}

export function operationalErrorMessage(
  error: unknown,
  t: Translate,
  format: Format,
  fallbackKey: TranslationKey = "apiGenericError",
): string {
  const apiError = asApiError(error);
  if (!apiError) return t(error instanceof Error && error.name === "AbortError" ? "apiRequestCancelled" : "apiNetworkError");
  const key = codeTranslationKeys[apiError.code] ?? (apiError.code === "api_error" ? fallbackKey : statusTranslationKey(apiError.status));
  return withRequestId(t(key), apiError.requestId, format);
}

export function operationalCodeMessage(
  code: string | null | undefined,
  t: Translate,
  format: Format,
  fallbackKey: TranslationKey = "apiGenericError",
  requestId?: string,
): string {
  const key = code ? codeTranslationKeys[code] ?? fallbackKey : fallbackKey;
  return withRequestId(t(key), requestId, format);
}
