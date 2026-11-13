import type { PipelineStepSummary } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18n";
import type { FeedbackTone } from "./feedback";

export type OcrProgress = Pick<PipelineStepSummary, "input_mode" | "processed_pages" | "total_pages" | "error_code" | "error_message" | "retry_allowed" | "ocr_call_state" | "page_output_token_limit" | "request_output_token_limit" | "page_map_status" | "source_precision" | "document_output_token_limit" | "confirmed_output_tokens" | "remaining_output_tokens" | "chunking_issue">;


/** Shared by pipeline status, upload refusals, and model configuration errors. */
export const OCR_NATIVE_ERROR_KEYS: Record<string, TranslationKey> = {
  ocr_document_provider_result_unknown: "ocrNativeResultUnknown",
  ocr_document_recovery_required: "ocrNativeRecoveryRequired",
  ocr_native_result_unconfirmed: "ocrNativeResultUnknown",
  ocr_document_receipt_conflict: "ocrNativeReceiptConflict",
  ocr_native_capability_required: "ocrNativeCapabilityRequired",
  ocr_native_model_required: "ocrNativeCapabilityRequired",
  ocr_native_endpoint_invalid: "ocrNativeCapabilityRequired",
  ocr_native_input_unsupported: "ocrNativeInputUnsupported",
  ocr_native_revision_required: "ocrModelSnapshotChanged",
  ocr_native_output_limit_invalid: "ocrTokenSettingsInvalid",
  ocr_source_identity_mismatch: "ocrNativeReceiptConflict",
  ocr_native_provider_failed: "ocrProviderUnavailable",
  ocr_native_refused: "ocrProviderRejected",
  ocr_native_response_invalid: "ocrProviderInvalidResponse",
  ocr_native_usage_missing: "ocrTokenUsageUnknown",
  ocr_native_response_too_large: "ocrProviderInvalidResponse",
  ocr_native_result_unknown: "ocrNativeResultUnknown",
  ocr_native_receipt_conflict: "ocrNativeReceiptConflict",
  ocr_native_response_incomplete: "ocrNativeResponseIncomplete",
  ocr_native_capability_invalid: "ocrNativeCapabilityRequired",
  ocr_native_input_too_large: "ocrNativeInputTooLarge",
  ocr_native_request_too_large: "ocrNativeInputTooLarge",
  ocr_request_too_large: "ocrNativeInputTooLarge",
  ocr_response_too_large: "ocrProviderInvalidResponse",
  ocr_native_context_exceeded: "ocrNativeContextExceeded",
  ocr_native_token_count_unavailable: "ocrNativeCountRequired",
  ocr_native_temperature_invalid: "ocrNativeConfigurationInvalid",
  ocr_native_tls_invalid: "ocrNativeConfigurationInvalid",
  ocr_timeout_config_invalid: "ocrNativeConfigurationInvalid",
  ocr_model_required: "ocrNativeCapabilityRequired",
  ocr_model_name_required: "ocrNativeCapabilityRequired",
  ocr_provider_unsupported: "ocrNativeCapabilityRequired",
  invalid_ocr_model: "ocrNativeCapabilityRequired",
  ocr_model_credential_required: "apiConfigurationRequired",
  ocr_page_token_setting_retired: "ocrPageTokenSettingRetired",
  ocr_adapter_not_configured: "apiConfigurationRequired",
  ocr_adapter_credential_required: "apiConfigurationRequired",
  ocr_adapter_provider_rejected: "ocrProviderRejected",
  ocr_adapter_unavailable: "ocrProviderUnavailable",
  ocr_adapter_response_invalid: "ocrProviderInvalidResponse",
  ocr_adapter_invalid_markdown: "ocrProviderInvalidResponse",
  ocr_source_file_missing: "remoteFileUnavailable",
  ocr_usage_missing: "ocrTokenUsageUnknown",
  ocr_pdf_document_timeout: "ocrProcessingTimeout",
};

export function ocrFailureKey(step?: Partial<OcrProgress> | null, message?: string | null): TranslationKey {
  const keys: Record<string, TranslationKey> = {
    chunk_atomic_unit_too_large: "chunkAtomicUnitTooLarge",
    chunk_model_capacity_unavailable: "chunkModelCapacityUnavailable",
    chunk_source_unresolved: "chunkSourceUnresolved",
    ...OCR_NATIVE_ERROR_KEYS,
    ocr_page_output_limit_exceeded: "ocrPageOutputLimitExceeded",
    ocr_document_output_budget_exhausted: "ocrDocumentOutputBudgetExhausted",
    ocr_token_settings_missing: "ocrTokenSettingsMissing",
    ocr_token_settings_invalid: "ocrTokenSettingsInvalid",
    ocr_image_provider_result_unknown: "ocrImageResultUnknown",
    ocr_image_receipt_conflict: "ocrImageReceiptConflict",
    ocr_model_snapshot_changed: "ocrModelSnapshotChanged",
    ocr_pdf_page_incomplete: "ocrImagePageIncomplete",
    ocr_pdf_budget_exhausted: "ocrImageBudgetExceeded",
    ocr_pdf_usage_missing: "ocrTokenUsageUnknown",
    ocr_adapter_provider_rejected: "ocrProviderRejected",
    ocr_adapter_unavailable: "ocrProviderUnavailable",
    ocr_pdf_page_timeout: "ocrProcessingTimeout",
    ocr_pdf_document_timeout: "ocrProcessingTimeout",
    ocr_adapter_response_invalid: "ocrProviderInvalidResponse",
    ocr_adapter_invalid_markdown: "ocrProviderInvalidResponse",
    ocr_adapter_credential_required: "apiConfigurationRequired",
    model_credential_invalid: "systemModelCredentialInvalid",
    model_usage_persistence_unconfirmed: "modelUsagePersistenceUnconfirmed",
    embedding_usage_identity_conflict: "modelUsagePersistenceUnconfirmed",
    embedding_build_provider_result_unknown: "embeddingBuildResultUnknown",
    content_update_provider_result_unknown: "contentEditModelUnknown",
    runtime_secret_unavailable: "systemCredentialReferenceUnavailable",
    runtime_secret_reference_denied: "systemCredentialReferenceDenied",
    legacy_model_credential_forbidden: "systemLegacyCredentialForbidden",
    ocr_adapter_not_configured: "apiConfigurationRequired",
    ocr_partial_retry_requires_review: "ocrImagePartialReview",
  };
  if (step?.error_code && keys[step.error_code]) return keys[step.error_code];
  const safeMessage = message ?? step?.error_message;
  if (safeMessage === "A PDF page OCR response is incomplete") return "ocrImagePageIncomplete";
  if (safeMessage === "PDF OCR exceeded its document-wide time or token budget" || safeMessage === "PDF OCR exceeded its document-wide token budget") return "ocrImageBudgetExceeded";
  if (safeMessage === "OCR model configuration changed; create a new extraction revision") return "ocrModelSnapshotChanged";
  if (safeMessage === "PDF processing failed; output was not accepted") return "knowledgeDetailPdfProcessingFailed";
  if (safeMessage === "OCR output settings must be initialized") return "ocrTokenSettingsMissing";
  if (safeMessage?.startsWith("OCR output ") && safeMessage.includes("invalid")) return "ocrTokenSettingsInvalid";
  return "apiGenericError";
}

export function ocrRetryBlocked(step?: Partial<OcrProgress> | null): boolean {
  return step?.retry_allowed === false || Boolean(step?.input_mode === "page_images" && ((step.processed_pages ?? 0) > 0 || step.error_code === "ocr_image_provider_result_unknown"));
}

/** Outcome classification comes from the contract, never translated text. */
export function ocrFailureTone(step?: Partial<OcrProgress> | null): FeedbackTone {
  return ["ocr_document_provider_result_unknown", "ocr_document_recovery_required", "ocr_native_result_unconfirmed", "ocr_native_usage_missing", "ocr_native_result_unknown", "ocr_image_provider_result_unknown", "ocr_pdf_usage_missing", "model_usage_persistence_unconfirmed", "embedding_build_provider_result_unknown", "content_update_provider_result_unknown", "embedding_usage_identity_conflict"].includes(step?.error_code ?? "") ? "warning" : "error";
}

export function ocrRetryBlockReasonKey(step?: Partial<OcrProgress> | null): TranslationKey | null {
  if (!ocrRetryBlocked(step)) return null;
  if (step?.error_code?.startsWith("chunk_")) return "chunkIssueRetryBlocked";
  if (step?.input_mode === "native_pdf") return ["ocr_document_provider_result_unknown", "ocr_native_result_unconfirmed"].includes(step.error_code ?? "") ? "ocrNativeResultUnknown" : "ocrNativeRecoveryRequired";
  return step?.error_code === "ocr_image_provider_result_unknown" ? "ocrImageResultUnknown" : "ocrImagePartialReview";
}
