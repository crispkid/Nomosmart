import type { FeedbackTone } from "./feedback";
import type { TranslationKey } from "./i18n";

export type ContentUpdateFeedback = { tone: FeedbackTone; message: TranslationKey; reasonCode?: string };
export function contentUpdateFeedback(update: { status: string; promoted?: boolean; error_code?: string | null; cleanup?: { status: string } | null } | null | undefined,
  notice: "submitted" | "recovery_cancelled" | null): ContentUpdateFeedback | null {
  if (!update) {
    if (notice === "recovery_cancelled") return { tone: "info", message: "contentEditRecoveryCancelled" };
    return notice === "submitted" ? { tone: "info", message: "contentEditSyncing" } : null;
  }
  if (update.status === "cancelled") return { tone: "info", message: "contentEditRecoveryCancelled" };
  if (update.error_code === "model_usage_persistence_unconfirmed") return { tone: "warning", message: "modelUsagePersistenceUnconfirmed", reasonCode: update.error_code };
  if (["content_update_provider_result_unknown", "embedding_build_provider_result_unknown", "ocr_image_provider_result_unknown"].includes(update.error_code ?? "")) return { tone: "warning", message: "contentEditModelUnknown", reasonCode: update.error_code! };
  if (update.status === "blocked") return { tone: "warning", message: "contentEditModelUnknown", reasonCode: update.error_code ?? undefined };
  if (update.status === "chunks_required") return { tone: "warning", message: "contentEditNoChunks" };
  if (update.status === "failed") return { tone: "error", message: update.promoted ? "contentEditCleanupFailed" : "contentEditSyncFailed" };
  if (["queued", "running"].includes(update.status) || (update.status === "ready" && update.cleanup && update.cleanup.status !== "completed")) return { tone: "info", message: update.promoted ? "contentEditCleaning" : "contentEditSyncing" };
  if (update.status === "ready") return { tone: "success", message: "contentEditSaved" };
  return { tone: "warning", message: "contentEditStatusUnconfirmed" };
}
