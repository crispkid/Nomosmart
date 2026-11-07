"use client";

import { FeedbackField } from "@/components/FeedbackMessage";
import { IconActionButton } from "@/components/IconActionButton";
import { useEffect, useRef, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { useI18n } from "@/lib/i18nClient";
import { getKnowledgeArtifactBlob, type OriginalFileViewerMetadata } from "@/lib/api";

export function OriginalFileDownload({ metadata, compact = false, onFailureChange }: { metadata?: OriginalFileViewerMetadata | null; compact?: boolean; onFailureChange?: (failed: boolean) => void }) {
  const { apiFetch } = useAuth();
  const { t } = useI18n();
  const [state, setState] = useState<{ path?: string; busy: boolean; failed: boolean }>({ busy: false, failed: false });
  const controller = useRef<AbortController | null>(null);
  const path = metadata?.download_url ?? undefined;
  const busy = state.path === path && state.busy, failed = state.path === path && state.failed;
  useEffect(() => () => controller.current?.abort(), [path]);
  useEffect(() => { onFailureChange?.(failed); }, [failed, onFailureChange]);
  if (!path) return null;
  async function download() {
    if (controller.current && !controller.current.signal.aborted) return;
    const request = new AbortController();
    controller.current = request;
    setState({ path, busy: true, failed: false });
    try {
      const blob = await getKnowledgeArtifactBlob(apiFetch, path!, request.signal);
      if (request.signal.aborted) return;
      const url = URL.createObjectURL(blob), anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = metadata?.original_file_name ?? "document";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      if (!request.signal.aborted) setState({ path, busy: false, failed: true });
    } finally {
      if (controller.current === request) controller.current = null;
      if (!request.signal.aborted) setState(previous => ({ ...previous, busy: false }));
    }
  }
  const label = t(busy ? "documentDownloadBusy" : "knowledgeDetailDownloadOriginal");
  const icon = busy ? <Loader2 className="spin" size={compact ? 18 : 15} aria-hidden="true" /> : <Download size={compact ? 18 : 15} aria-hidden="true" />;
  return <div className={`original-file-download${compact ? " compact" : ""}`}>
    {compact ? <IconActionButton className="action-button secondary" label={label} disabled={busy} aria-busy={busy} onClick={download}>{icon}</IconActionButton> :
      <button className="action-button secondary" disabled={busy} onClick={download} type="button">{icon}{label}</button>}
    {failed && !(compact && onFailureChange) ? <FeedbackField>{t("knowledgeDetailDownloadFailed")}</FeedbackField> : null}
  </div>;
}
