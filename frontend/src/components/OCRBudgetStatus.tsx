"use client";
import type { OcrProgress } from "@/lib/ocrPresentation";
import { useI18n } from "@/lib/i18nClient";
import { formatCount } from "@/lib/numberFormat";

export function OCRBudgetStatus({ step }: { step?: Partial<OcrProgress> | null }) {
  const { format, t, locale } = useI18n();
  if (step?.input_mode !== "page_images") return null;
  return <div className="pipeline-meta ocr-budget-status" aria-live="polite">
    {step.total_pages != null ? <span>{format("knowledgeDetailImageOcrPages", { completed: formatCount(step.processed_pages ?? 0, locale), total: formatCount(step.total_pages, locale) })}</span> : null}
    {step.page_output_token_limit != null && step.document_output_token_limit != null ? <span>{format("ocrBudgetLimits", { page: formatCount(step.page_output_token_limit, locale), document: formatCount(step.document_output_token_limit, locale) })}</span> : null}
    {step.document_output_token_limit != null ? <span>{step.confirmed_output_tokens == null ? t(step.ocr_call_state === "in_flight" ? "ocrPageResponsePending" : "ocrTokenUsageUnknown") : format("ocrBudgetUsage", { used: formatCount(step.confirmed_output_tokens, locale), remaining: step.remaining_output_tokens == null ? "—" : formatCount(step.remaining_output_tokens, locale) })}</span> : null}
  </div>;
}
