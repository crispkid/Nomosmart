/** Only a failure at the actual fetch boundary is classified as transport failure. */
import type { TranslationKey } from "./i18n";

export class UiValidationError extends Error {
  readonly key: TranslationKey;
  constructor(key: TranslationKey) { super("ui_validation_failed"); this.name = "UiValidationError"; this.key = key; }
}
export class TransportError extends Error {
  constructor() { super("api_transport_unavailable"); this.name = "TransportError"; }
}
export class MutationOutcomeUnknown extends Error {
  constructor() { super("operation_outcome_unknown"); this.name = "MutationOutcomeUnknown"; }
}
/** These are existing response contracts, not guesses based on exception text. */
export function isMutationResultUnknown(error: unknown): boolean {
  if (error instanceof MutationOutcomeUnknown) return true;
  if (!(error instanceof Error)) return false;
  const response = error as Error & { status?: number; code?: string };
  return typeof response.status === "number" && ((response.status >= 500 && response.code === "api_error") || ["backend_proxy_unreachable", "model_usage_persistence_unconfirmed", "embedding_build_provider_result_unknown", "ocr_image_provider_result_unknown", "content_update_provider_result_unknown"].includes(response.code ?? ""));
}
export async function transportFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = new Request(input, init);
  try { return await fetch(request); }
  catch (error) {
    if (init?.signal?.aborted || (error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError"))) throw error;
    if (error instanceof TypeError) throw new TransportError();
    throw error;
  }
}
