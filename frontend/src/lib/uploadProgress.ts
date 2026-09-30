/** UI notice only: never a request deadline or a processing percentage. */
export function uploadWaitNoticeMs(value?: unknown): number {
  if (value === undefined) return 30_000;
  if (typeof value !== "number" && (typeof value !== "string" || !/^\d+$/.test(value))) {
    throw new Error("invalid_upload_wait_notice");
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1_000 || parsed > 300_000) throw new Error("invalid_upload_wait_notice");
  return parsed;
}

export type UploadReceipt = {
  index: number;
  status: "success" | "failed";
  documentId?: string | null;
  versionId?: string | null;
  errorCode?: string | null;
};
export type UploadBatchResult<T> = { documents: T[]; receipts: UploadReceipt[] };
export type UploadFileResult = { name: string; ok: boolean; reason: string };

/** Reconcile by submitted index (not filename); duplicates may be valid files. */
export function confirmedUploadResults(validation: UploadFileResult[], receipts: UploadReceipt[]): UploadFileResult[] {
  const submitted = validation.filter((item) => item.ok);
  if (receipts.length !== submitted.length || new Set(receipts.map((item) => item.index)).size !== submitted.length ||
    receipts.some((item) => !Number.isInteger(item.index) || item.index < 0 || item.index >= submitted.length ||
      !["success", "failed"].includes(item.status) ||
      (item.status === "success" && (!item.documentId || !item.versionId)))) {
    throw new Error("upload_result_unconfirmed");
  }
  let index = 0;
  return validation.map((item) => {
    if (!item.ok) return item;
    const submittedIndex = index++;
    const receipt = receipts.find((entry) => entry.index === submittedIndex)!;
    return receipt.status === "success" ? item : { ...item, ok: false, reason: "server:" + (receipt.errorCode || "document_upload_failed") };
  });
}

export function uploadOutcomeUnknown(error: unknown): boolean {
  const status = error && typeof error === "object" && "status" in error ? error.status : undefined;
  // A gateway failure, conflict/in-progress, lost body or transport error cannot
  // prove that the server did not commit. Never suggest automatic replay.
  return ![400, 401, 403, 404, 413, 415, 422].includes(status as number);
}

export function confirmedPipelinePercent(pipeline?: { id?: string | null; progress: number; steps?: unknown[] }): number | null {
  if (!pipeline?.id || !pipeline.steps?.length || !Number.isFinite(pipeline.progress)) return null;
  return Math.min(100, Math.max(0, Math.round(pipeline.progress)));
}

/** Attempt ownership is separate from visibility and the underlying request. */
export class UploadAttemptGuard {
  private sequence = 0;
  private pending = false;
  private visible = false;

  begin(): number {
    if (this.pending) throw new Error("upload_already_pending");
    this.pending = true;
    this.visible = true;
    return ++this.sequence;
  }
  accepts(attempt: number): boolean { return attempt === this.sequence; }
  current(): number { return this.sequence; }
  canPresent(attempt: number): boolean { return this.accepts(attempt) && this.visible; }
  isPending(): boolean { return this.pending; }
  leave(): void { this.visible = false; }
  finish(attempt: number): void { if (this.accepts(attempt)) this.pending = false; }
  invalidate(): void { this.sequence += 1; this.pending = false; this.visible = false; }
}
