"use client";

import { Clock3, AlertTriangle } from "lucide-react";
import type { PipelineExecution } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

const phaseLabels: Record<string, TranslationKey> = {
  queued: "fileProcessingQueued", starting_parser: "fileProcessingStarting",
  parsing: "fileProcessingParsing", waiting_worker: "fileProcessingWaitingWorker",
  processing: "fileProcessingProcessing", stopping: "fileProcessingStopping",
  recovery_required: "fileProcessingRecovery", completed: "fileProcessingCompleted",
  failed: "fileProcessingFailed", cancelled: "fileProcessingCancelled"
};

export function FileProcessingStatus({ execution, queued = false, cleanupUnconfirmed = false }: { execution?: PipelineExecution | null; queued?: boolean; cleanupUnconfirmed?: boolean }) {
  const { t, format } = useI18n();
  if (!execution && !queued) return null;
  const label = cleanupUnconfirmed ? "fileProcessingCleanupUnconfirmed" : phaseLabels[execution?.phase ?? "queued"] ?? "fileProcessingUnknown";
  const attention = cleanupUnconfirmed || execution?.phase === "recovery_required" || execution?.phase === "failed";
  const Icon = attention ? AlertTriangle : Clock3;
  const count = execution?.completed_units;
  const total = execution?.total_units;
  const validPages = execution?.unit === "pages" && Number.isInteger(count) && count! >= 0 &&
    (total === null || (Number.isInteger(total) && total! >= count!));
  return (
    <div className="pipeline-meta" role="status" aria-live="polite" aria-atomic="true">
      <Icon size={16} aria-hidden="true" />
      <span>{t(label)}</span>
      {validPages ? <span>{total === null
        ? format("fileProcessingPagesUnknown", { completed: count! })
        : format("fileProcessingPagesKnown", { completed: count!, total: total! })}</span> : null}
      {attention && !cleanupUnconfirmed ? <span>{t("fileProcessingRecoveryHelp")}</span> : null}
    </div>
  );
}
