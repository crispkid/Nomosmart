"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Extension } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import { Markdown } from "@tiptap/markdown";
import { AlertTriangle, Bold, Columns2, Download, Italic, List, ListOrdered, Loader2, Save, Table2, X } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { SafeMarkdown } from "./SafeMarkdown";
import { getKnowledgeArtifactBlob, type ApiError } from "@/lib/api";
import { cancelFailedContent, getContentEditor, saveContent, type ContentEditorSource, type ContentUpdateResult } from "@/lib/documentContentApi";
import { preserveSource, sourceDocument, utf16Offset, type SourceDocument } from "@/lib/contentEditorSource";
import { useI18n } from "@/lib/i18nClient";

const SourceIdentity = Extension.create({ name: "contentSourceIdentity", addGlobalAttributes() {
  return [{ types: ["paragraph", "heading", "bulletList", "orderedList", "blockquote", "codeBlock", "table", "horizontalRule"],
    attributes: { contentSourceId: { default: null, rendered: false } } }];
} });

export function DocumentContentEditorModal({ projectId, documentId, versionId, chunkId, onClose, onSaved }: {
  projectId: string; documentId: string; versionId: string; chunkId?: string;
  onClose: () => void; onSaved: (result: ContentUpdateResult) => Promise<void>;
}) {
  const { apiFetch } = useAuth();
  const { t, format } = useI18n();
  const [source, setSource] = useState<ContentEditorSource | null>(null);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"rich" | "text">("text");
  const [compare, setCompare] = useState(false);
  const [original, setOriginal] = useState<{ url?: string; text?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState(false);
  const [conversionError, setConversionError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [confirmCancelUpdate, setConfirmCancelUpdate] = useState(false);
  const cancelKey = useRef<string | null>(null);
  const documentRef = useRef<SourceDocument | null>(null);
  const rawRef = useRef<HTMLTextAreaElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastRequest = useRef<{ key: string; markdown: string } | null>(null);
  const readyRef = useRef(false);
  const editor = useEditor({ immediatelyRender: false, extensions: [
    StarterKit.configure({ link: { openOnClick: false, autolink: false } }),
    Table.configure({ resizable: false }), TableCell.extend({ content: "paragraph" }), TableHeader.extend({ content: "paragraph" }),
    TableRow, SourceIdentity, Markdown,
  ], editable: false, editorProps: { attributes: { class: "content-edit-rich", "aria-label": t("contentEditFullText") } },
    onUpdate: ({ editor: current }) => {
      if (!readyRef.current || !documentRef.current || !current.markdown) return;
      try { setDraft(preserveSource(documentRef.current, current.getJSON(), current.markdown)); setConversionError(false); }
      catch { setConversionError(true); }
    }
  });
  const dirty = Boolean(source && draft !== (source.failed_update?.pending_markdown ?? source.markdown)) || conversionError;
  const requestClose = useCallback(() => {
    if (busy) return;
    if (dirty) setConfirmDiscard(true); else onClose();
  }, [busy, dirty, onClose]);

  useEffect(() => {
    const controller = new AbortController();
    getContentEditor(apiFetch, projectId, documentId, versionId, chunkId, controller.signal).then(value => {
      if (!controller.signal.aborted) { setSource(value); setDraft(value.failed_update?.pending_markdown ?? value.markdown); }
    }).catch(() => { if (!controller.signal.aborted) setError(t("contentEditLoadFailed")); });
    return () => controller.abort();
  }, [apiFetch, projectId, documentId, versionId, chunkId, t]);

  useEffect(() => {
    if (!source || !editor?.markdown || readyRef.current) return;
    const initialize = () => {
      const parsed = sourceDocument(source.failed_update?.pending_markdown ?? source.markdown, editor.markdown!);
      documentRef.current = parsed;
      if (parsed) { editor.commands.setContent(parsed.json, { emitUpdate: false }); setMode("rich"); }
      else { setMode("text"); setWarning(true); }
      editor.setEditable(source.edit_mode !== "readonly");
      readyRef.current = true;
    };
    // Initialization is driven by the asynchronously loaded source/editor,
    // rather than a synchronous cascading render from the effect body.
    const task = requestAnimationFrame(initialize);
    return () => cancelAnimationFrame(task);
  }, [source, editor]);

  useEffect(() => { editor?.setEditable(Boolean(source && source.edit_mode !== "readonly" && !busy)); }, [source, editor, busy]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); else document.querySelector<HTMLAnchorElement>(".project-context a")?.focus(); };
  }, []);

  useEffect(() => {
    if (!source?.selection_ranges.length || source.failed_update) return;
    const selection = source.selection_ranges[0];
    if (mode === "text" && rawRef.current) {
      rawRef.current.focus();
      rawRef.current.setSelectionRange(utf16Offset(source.markdown, selection.start), utf16Offset(source.markdown, selection.end));
    } else if (editor && documentRef.current) {
      const start = utf16Offset(source.markdown, selection.start);
      const entry = [...documentRef.current.blocks].find(([, block]) => block.start <= start && start < block.end);
      if (entry) editor.state.doc.forEach((node, offset) => {
        if (node.attrs.contentSourceId === entry[0]) editor.commands.setTextSelection({ from: offset + 1, to: offset + node.nodeSize - 1 });
      });
    }
  }, [source, mode, editor]);

  useEffect(() => {
    if (!compare || !source?.original_file) return;
    let cancelled = false, url: string | null = null;
    const metadata = source.original_file;
    const path = metadata.preview_url || metadata.download_url;
    if (!path) return;
    getKnowledgeArtifactBlob(apiFetch, path).then(async blob => {
      if (cancelled) return;
      if (blob.type.startsWith("text/") || metadata.viewer_type === "markdown") {
        const text = await blob.text(); if (!cancelled) setOriginal({ text });
      } else if (blob.type === "application/pdf" || blob.type.startsWith("image/")) {
        url = URL.createObjectURL(blob); setOriginal({ url });
      }
    }).catch(() => { if (!cancelled) setOriginal(null); });
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [apiFetch, compare, source]);

  function switchMode(next: "rich" | "text") {
    if (!editor?.markdown || busy || conversionError) return;
    if (next === "rich") {
      const parsed = sourceDocument(draft, editor.markdown);
      if (!parsed) { setWarning(true); return; }
      documentRef.current = parsed;
      editor.commands.setContent(parsed.json, { emitUpdate: false });
      setWarning(false);
    }
    setMode(next);
  }
  async function save() {
    if (!source || conversionError || source.edit_mode === "readonly") return;
    setBusy(true); setError(null);
    if (!lastRequest.current || lastRequest.current.markdown !== draft) lastRequest.current = { key: crypto.randomUUID(), markdown: draft };
    try {
      const result = await saveContent(apiFetch, source, draft, lastRequest.current.key);
      await onSaved(result); onClose();
    } catch (caught) {
      const code = (caught as Partial<ApiError>).code;
      setError(t(code === "content_edit_legacy_chunk_conflict" ? "contentEditLegacyConflict" : code === "content_edit_conflict" ? "contentEditConflict" : code === "content_edit_too_large" ? "contentEditTooLarge" : "contentEditSaveFailed"));
    } finally { setBusy(false); }
  }
  async function cancelUpdate() {
    if (!source?.failed_update?.can_cancel || busy) return;
    setBusy(true); setError(null);
    cancelKey.current ??= crypto.randomUUID();
    try {
      const result = await cancelFailedContent(apiFetch, source, cancelKey.current);
      await onSaved(result); onClose();
    } catch (caught) {
      setError(t((caught as Partial<ApiError>).code === "content_edit_conflict" ? "contentEditConflict" : "contentEditCancelFailed"));
    } finally { setBusy(false); }
  }
  const size = new TextEncoder().encode(draft).length;
  return <div className="modal-backdrop content-edit-backdrop" onKeyDown={event => {
    if (event.key === "Escape") { event.stopPropagation(); requestClose(); }
    if (event.key === "Tab") {
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled),select:not(:disabled),textarea:not(:disabled),[contenteditable=true],a[href]") ?? []).filter(item => item.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}>
    <section ref={dialogRef} className="modal-panel content-edit-modal" role="dialog" aria-modal="true" aria-labelledby="content-edit-title">
      <header className="modal-header"><div><h2 id="content-edit-title">{t("contentEditTitle")}</h2><p>{source ? `${source.document_title} · ${source.version_label}` : t("loadingData")}</p></div>
        <button ref={closeRef} type="button" className="modal-close-button" aria-label={t("close")} onClick={requestClose} disabled={busy}><X size={18} /></button></header>
      <div className="content-edit-version-note" role="status">{t(source?.edit_mode === "create_revision" ? "contentEditNewVersionHelp" : "contentEditWorkingHelp")}</div>
      {source?.failed_update ? <div className="content-edit-warning" role="status"><AlertTriangle size={16} />{t("contentEditRecoveryHelp")}</div> : null}
      {error ? <div className="error-summary" role="alert">{error}</div> : null}
      {warning || conversionError ? <div className="content-edit-warning" role="status"><AlertTriangle size={16} />{t(conversionError ? "contentEditConversionFailed" : "contentEditTextModeHelp")}</div> : null}
      {source?.selection_reason ? <div className="content-edit-warning" role="status">{t("contentEditSelectionUnavailable")}</div> : null}
      <div className="content-edit-toolbar" role="group" aria-label={t("contentEditTools")}>
        <button type="button" className="action-button secondary" aria-pressed={mode === "rich"} onClick={() => switchMode("rich")} disabled={!source || busy || source.edit_mode === "readonly"}>{t("contentEditRichMode")}</button>
        <button type="button" className="action-button secondary" aria-pressed={mode === "text"} onClick={() => switchMode("text")} disabled={!source || busy}>{t("contentEditTextMode")}</button>
        {mode === "rich" ? <>
          <select aria-label={t("contentEditParagraphStyle")} disabled={!editor || busy || source?.edit_mode === "readonly"} onChange={event => {
            if (event.target.value === "p") editor?.chain().focus().setParagraph().run();
            else editor?.chain().focus().toggleHeading({ level: Number(event.target.value) as 1 | 2 | 3 }).run();
          }} defaultValue="p"><option value="p">{t("contentEditParagraph")}</option><option value="1">{t("contentEditHeading1")}</option><option value="2">{t("contentEditHeading2")}</option><option value="3">{t("contentEditHeading3")}</option></select>
          <button type="button" aria-label={t("contentEditBold")} onClick={() => editor?.chain().focus().toggleBold().run()} disabled={busy || source?.edit_mode === "readonly"}><Bold size={16} /></button>
          <button type="button" aria-label={t("contentEditItalic")} onClick={() => editor?.chain().focus().toggleItalic().run()} disabled={busy || source?.edit_mode === "readonly"}><Italic size={16} /></button>
          <button type="button" aria-label={t("contentEditBulletList")} onClick={() => editor?.chain().focus().toggleBulletList().run()} disabled={busy || source?.edit_mode === "readonly"}><List size={16} /></button>
          <button type="button" aria-label={t("contentEditOrderedList")} onClick={() => editor?.chain().focus().toggleOrderedList().run()} disabled={busy || source?.edit_mode === "readonly"}><ListOrdered size={16} /></button>
          <button type="button" aria-label={t("contentEditTable")} onClick={() => editor?.chain().focus().insertTable({ rows: 3, cols: 2, withHeaderRow: true }).run()} disabled={busy || source?.edit_mode === "readonly"}><Table2 size={16} /></button>
        </> : null}
        <button type="button" className="action-button secondary content-edit-compare" aria-pressed={compare} onClick={() => setCompare(value => !value)}><Columns2 size={16} />{t("contentEditCompare")}</button>
      </div>
      <div className={compare ? "content-edit-body with-original" : "content-edit-body"}>
        <div className="content-edit-document">{!source ? <div className="empty-state compact"><Loader2 size={18} />{t("loadingData")}</div> : mode === "rich" ? <EditorContent editor={editor} /> : <textarea ref={rawRef} aria-label={t("contentEditFullText")} value={draft} readOnly={source.edit_mode === "readonly"} disabled={busy} onChange={event => setDraft(event.target.value)} spellCheck={false} />}</div>
        {compare ? <aside className="content-edit-original"><h3>{t("contentEditOriginalReadonly")}</h3>
          {original?.text !== undefined ? <SafeMarkdown source={original.text} /> : original?.url ? <iframe src={original.url} title={t("contentEditOriginalReadonly")} /> : <p>{t("contentEditOriginalDownloadHelp")}</p>}
          {source?.original_file?.download_url ? <button type="button" className="action-button secondary" onClick={() => {
            getKnowledgeArtifactBlob(apiFetch, source.original_file!.download_url!).then(blob => {
              const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url;
              anchor.download = source.original_file?.original_file_name || source.document_title; anchor.click(); URL.revokeObjectURL(url);
            }).catch(() => setError(t("knowledgeDetailDownloadFailed")));
          }}><Download size={16} />{t("knowledgeDetailDownloadOriginal")}</button> : null}
        </aside> : null}
      </div>
      {confirmDiscard ? <div className="content-edit-discard" role="alert"><span>{t("contentEditUnsaved")}</span><button type="button" className="action-button secondary" onClick={() => setConfirmDiscard(false)}>{t("contentEditContinue")}</button><button type="button" className="action-button secondary" onClick={onClose}>{t("contentEditDiscard")}</button></div> : null}
      {confirmCancelUpdate ? <div className="content-edit-discard" role="alert"><span>{t("contentEditCancelConfirm")}</span><button type="button" className="action-button secondary" disabled={busy} onClick={() => setConfirmCancelUpdate(false)}>{t("contentEditContinue")}</button><button type="button" className="action-button secondary" disabled={busy} onClick={() => void cancelUpdate()}>{t("contentEditCancelUpdate")}</button></div> : null}
      <footer className="content-edit-footer"><div><p>{t("contentEditSyncHelp")}</p>{source ? <small>{format("contentEditSize", { bytes: size, limit: source.max_utf8_bytes })}</small> : null}</div>
        {source?.failed_update?.can_cancel ? <button type="button" className="action-button secondary" disabled={busy} onClick={() => setConfirmCancelUpdate(true)}>{t("contentEditCancelUpdate")}</button> : null}
        <button type="button" className="action-button secondary" onClick={requestClose} disabled={busy}>{t("cancel")}</button>
        <button type="button" className="action-button" onClick={() => void save()} disabled={!source || busy || source.edit_mode === "readonly" || conversionError || size > source.max_utf8_bytes}>{busy ? <Loader2 className="spin" size={16} /> : <Save size={16} />}{t(source?.edit_mode === "create_revision" ? "contentEditSaveNewVersion" : "contentEditSave")}</button>
      </footer>
    </section>
  </div>;
}
