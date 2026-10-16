import type { ApiError } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18n";
import { MutationOutcomeUnknown, TransportError, UiValidationError } from "./transportError.ts";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

const codeTranslationKeys: Partial<Record<string, TranslationKey>> = {
  unsupported_upload_type: "uploadModalHelp",
  ftps_tls_verification_required: "ftpsTlsVerificationRequired",
  ftps_ca_unavailable: "ftpsCaUnavailable",
  ftps_certificate_invalid: "ftpsCertificateInvalid",
  remote_file_unavailable: "remoteFileUnavailable",
  remote_operation_unsupported: "remoteOperationUnsupported",
  invalid_file_signature: "uploadInvalidContent",
  notification_business_action_required: "notificationBusinessActionRequired",
  model_usage_persistence_unconfirmed: "modelUsagePersistenceUnconfirmed",
  embedding_build_in_progress: "embeddingBuildInProgress",
  embedding_build_provider_result_unknown: "embeddingBuildResultUnknown",
  embedding_usage_identity_conflict: "modelUsagePersistenceUnconfirmed",
  query_usage_identity_conflict: "queryUsageIdentityConflict",
  chunk_atomic_unit_too_large: "chunkAtomicUnitTooLarge",
  chunk_model_capacity_unavailable: "chunkModelCapacityUnavailable",
  chunk_source_unresolved: "chunkSourceUnresolved",
  ocr_token_settings_missing: "ocrTokenSettingsMissing",
  ocr_token_settings_invalid: "ocrTokenSettingsInvalid",
  ocr_token_settings_conflict: "ocrTokenSettingsConflict",
  ocr_page_output_limit_exceeded: "ocrPageOutputLimitExceeded",
  ocr_document_output_budget_exhausted: "ocrDocumentOutputBudgetExhausted",
  ocr_pdf_page_incomplete: "ocrImagePageIncomplete",
  ocr_pdf_usage_missing: "ocrTokenUsageUnknown",
  ocr_partial_retry_requires_review: "ocrImagePartialReview",
  ocr_image_provider_result_unknown: "ocrImageResultUnknown",
  ocr_image_receipt_conflict: "ocrImageReceiptConflict",
  ocr_model_snapshot_changed: "ocrModelSnapshotChanged",
  content_edit_conflict: "contentEditConflict",
  content_edit_too_large: "contentEditTooLarge",
  content_update_provider_result_unknown: "contentEditModelUnknown",
  chunk_content_source_unresolved: "contentEditSelectionUnavailable",
  content_edit_legacy_chunk_conflict: "contentEditLegacyConflict",
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
  model_credential_invalid: "systemModelCredentialInvalid",
  runtime_secret_unavailable: "systemCredentialReferenceUnavailable",
  runtime_secret_reference_denied: "systemCredentialReferenceDenied",
  legacy_model_credential_forbidden: "systemLegacyCredentialForbidden",
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
  return requestId && /^[A-Za-z0-9_-]{1,80}$/.test(requestId) ? format("apiErrorWithRequestId", { message, requestId }) : message;
}

export function operationalErrorMessage(
  error: unknown,
  t: Translate,
  format: Format,
  fallbackKey: TranslationKey = "apiGenericError",
): string {
  const apiError = asApiError(error);
  if (error instanceof UiValidationError) return t(error.key);
  if (!apiError) return t(error instanceof MutationOutcomeUnknown ? "feedbackResultUnknown" : error instanceof TransportError ? "apiNetworkError" : error instanceof Error && error.name === "AbortError" ? "apiRequestCancelled" : error instanceof Error && error.name === "TimeoutError" ? "feedbackResultUnknown" : fallbackKey);
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
