"use client";

import { useEffect } from "react";
import { Loader2, Trash2, X } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { VersionGraphPreview } from "@/components/VersionGraphPreview";
import { useModalFocus } from "@/components/useModalFocus";
import { useI18n } from "@/lib/i18nClient";

/**
 * Chunk delete confirmation on the knowledge detail page (D424-18). Mounted only
 * while open; Esc, the backdrop and the close buttons do nothing while busy.
 */
export function ChunkDeleteDialog({ chunk, busy, error, onCancel, onConfirm }: {
  chunk: { index: number; content: string }; busy: boolean; error: string | null; onCancel: () => void; onConfirm: () => void;
}) {
  const { t, format } = useI18n();
  const dialogRef = useModalFocus(true, () => { if (!busy) onCancel(); });
  return <div className="system-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }} role="presentation">
    <section ref={dialogRef} tabIndex={-1} aria-labelledby="delete-chunk-title" aria-modal="true" className="system-reauth-modal chunk-delete-modal" role="alertdialog">
      <header><span className="danger-icon"><Trash2 size={20} /></span><div><small>{format("knowledgeDetailChunkLabel", { number: chunk.index })}</small><h2 id="delete-chunk-title">{t("knowledgeDetailDeleteChunkTitle")}</h2></div><button aria-label={t("close")} className="modal-close-button" disabled={busy} onClick={onCancel} type="button"><X size={18} /></button></header>
      <p>{t("knowledgeDetailDeleteChunkHelp")}</p>
      <blockquote>{chunk.content.slice(0, 180)}{chunk.content.length > 180 ? "..." : ""}</blockquote>
      {error ? <FeedbackMessage tone="error"><strong>{error}</strong></FeedbackMessage> : null}
      <footer><button className="action-button secondary" disabled={busy} onClick={onCancel} type="button">{t("cancel")}</button><button className="action-button danger" disabled={busy} onClick={onConfirm} type="button">{busy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}{t("knowledgeDetailConfirmDeleteChunk")}</button></footer>
    </section>
  </div>;
}

/** Version graph preview dialog on the knowledge detail page (D424-18); locks page scroll while open. */
export function DocumentGraphDialog({ projectId, detail, onClose }: {
  projectId: string;
  detail: { document: { id: string; title: string }; version: { id: string; version_label: string } } | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useModalFocus(true, onClose);
  useEffect(() => {
    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.overflow = previousHtmlOverflow;
    };
  }, []);
  return (
    <div className="modal-backdrop">
      <section ref={dialogRef} tabIndex={-1} aria-labelledby="document-graph-title" aria-modal="true" className="modal-panel document-graph-modal" role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{detail ? `${detail.document.title} · ${detail.version.version_label}` : t("knowledgeDetailLiveGraphEyebrow")}</p>
            <h2 id="document-graph-title">{t("knowledgeGraphPreview")}</h2>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label={t("knowledgeDetailCloseGraphPreview")}>
            <X size={18} />
          </button>
        </div>
        {detail ? <VersionGraphPreview projectId={projectId} documentId={detail.document.id}
          versionId={detail.version.id} documentTitle={detail.document.title}
          version={detail.version.version_label} /> : null}
      </section>
    </div>
  );
}
