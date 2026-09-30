"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Check, CheckCircle2, Copy, FileText, FolderKanban, Layers3, LoaderCircle, RefreshCcw, Search, Trash2, X } from "lucide-react";
import type { ReferenceSourceDocumentResponse, ReferenceSourceProjectResponse, ReferenceSourceVersionResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

type Selection = {
  project: ReferenceSourceProjectResponse;
  document: ReferenceSourceDocumentResponse;
  version: ReferenceSourceVersionResponse;
};

type ImportResult = { createdCount: number; errors: string[] };

function selectionKey(projectId: string, documentId: string) {
  return `${projectId}:${documentId}`;
}

export function ProjectReferenceModal({
  sources,
  loading,
  error,
  onClose,
  onRefresh,
  onCreate
}: {
  sources: ReferenceSourceProjectResponse[];
  loading: boolean;
  error: string;
  onClose: () => void;
  onRefresh: () => void;
  onCreate: (mode: "reference" | "copy", items: Array<{ source_document_id: string; source_version_id: string; old_version_confirmed?: boolean }>) => Promise<ImportResult>;
}) {
  const { t, format, localize } = useI18n();
  const [mode, setMode] = useState<"reference" | "copy">("reference");
  const [projectId, setProjectId] = useState<string>(() => sources[0]?.id ?? "");
  const [query, setQuery] = useState("");
  const [selections, setSelections] = useState<Record<string, Selection>>({});
  const [oldRiskOpen, setOldRiskOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitErrors, setSubmitErrors] = useState<string[]>([]);
  const [resultCount, setResultCount] = useState<number | null>(null);
  const activeProject = sources.find((project) => project.id === projectId) ?? sources[0];
  const documents = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (activeProject?.documents ?? []).filter((document) => {
      const haystack = `${document.title} ${document.owner ?? ""}`.toLowerCase();
      return !normalized || haystack.includes(normalized);
    });
  }, [activeProject, query]);
  const selectedItems = Object.values(selections);

  function selectVersion(project: ReferenceSourceProjectResponse, document: ReferenceSourceDocumentResponse, version: ReferenceSourceVersionResponse) {
    if (mode === "reference" && document.duplicate) return;
    const key = selectionKey(project.id, document.id);
    if (mode === "reference") setSelections({ [key]: { project, document, version } });
    else setSelections((current) => ({ ...current, [key]: { project, document, version } }));
  }

  function switchMode(nextMode: "reference" | "copy") {
    setMode(nextMode);
    setOldRiskOpen(false);
    setSubmitErrors([]);
    if (nextMode === "reference" && selectedItems.length > 1) setSelections({});
  }

  async function execute() {
    const items = Object.values(selections);
    if (!items.length || submitting) return;
    const hasOldVersion = items.some((item) => item.version.status !== "active");
    if (hasOldVersion && !oldRiskOpen) {
      setOldRiskOpen(true);
      return;
    }
    setSubmitting(true);
    setSubmitErrors([]);
    try {
      const result = await onCreate(mode, items.map((item) => ({
        source_document_id: item.document.id,
        source_version_id: item.version.id,
        old_version_confirmed: item.version.status !== "active" ? oldRiskOpen : false
      })));
      setResultCount(result.createdCount);
      setSubmitErrors(result.errors);
      if (!result.errors.length && mode === "reference") onClose();
      if (!result.errors.length) setSelections({});
    } catch (caught) {
      setSubmitErrors([operationalErrorMessage(caught, t, format, "referenceCreateFailed")]);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-labelledby="reference-project-title" aria-modal="true" className="modal-panel reference-picker-modal" role="dialog">
        <div className="modal-header">
          <div><p className="eyebrow">{t("referenceModalEyebrow")}</p><h2 id="reference-project-title">{t("referenceModalTitle")}</h2></div>
          <button aria-label={t("referenceModalClose")} className="icon-button" onClick={onClose} type="button"><X size={18} /></button>
        </div>
        <div className="reference-mode-tabs">
          <button className={mode === "reference" ? "active" : ""} onClick={() => switchMode("reference")} type="button"><Layers3 size={16} /> {t("referenceModeReference")}</button>
          <button className={mode === "copy" ? "active" : ""} onClick={() => switchMode("copy")} type="button"><Copy size={16} /> {t("referenceModeCopy")}</button>
        </div>
        {resultCount !== null ? <div className="reference-result"><CheckCircle2 size={20} /><span><strong>{format("referenceResultTitle", { count: resultCount })}</strong><small>{t("referenceResultHelp")}</small></span></div> : null}
        {loading ? <div className="empty-state compact" role="status"><LoaderCircle size={22} /><p>{t("referenceLoadingSources")}</p></div> : null}
        {error ? <div className="error-summary" role="alert"><strong>{localize(error)}</strong><button className="text-link" onClick={onRefresh} type="button"><RefreshCcw size={15} /> {t("retry")}</button></div> : null}
        {!loading && !error && !sources.length ? <div className="empty-state compact"><FolderKanban size={24} /><p>{t("projectImportNoReferenceProjects")}</p></div> : null}
        {!loading && !error && sources.length ? (
          <div className="reference-picker-layout">
            <aside className="reference-projects">
              <strong>{t("referenceVisibleProjects")}</strong>
              {sources.map((project) => (
                <button className={project.id === activeProject?.id ? "active" : ""} key={project.id} onClick={() => { setProjectId(project.id); setQuery(""); }} type="button">
                  <FolderKanban size={16} />
                  <span><strong>{project.name}</strong><small>{format("referenceDocumentCount", { count: project.documents.length })}</small></span>
                </button>
              ))}
            </aside>
            <div className="reference-documents">
              <label className="reference-search"><Search size={15} /><input onChange={(event) => setQuery(event.target.value)} placeholder={t("referenceSearchPlaceholder")} value={query} /></label>
              <div className="reference-document-list">
                {documents.map((document) => {
                  const key = selectionKey(activeProject.id, document.id);
                  const selected = selections[key];
                  const disabledDuplicate = mode === "reference" && Boolean(document.duplicate);
                  return (
                    <article className={disabledDuplicate ? "duplicate" : ""} key={document.id}>
                      <div className="reference-document-head">
                        <FileText size={17} />
                        <div><strong>{document.title}</strong><small>{t("referenceOwner")} {document.owner ?? t("projectImportSystemSync")}</small></div>
                        {disabledDuplicate ? <span>{t("referenceDuplicate")}</span> : null}
                      </div>
                      {disabledDuplicate && document.duplicate ? <div className="reference-duplicate-note"><AlertTriangle size={14} /> {format("referenceDuplicateNote", { title: document.duplicate.target_title, version: document.duplicate.source_version_label })}</div> : (
                        <div className="reference-version-options">
                          {document.versions.map((version) => (
                            <button aria-pressed={selected?.version.id === version.id} className={selected?.version.id === version.id ? "selected" : ""} key={version.id} onClick={() => selectVersion(activeProject, document, version)} type="button">
                              <span className="reference-radio">{selected?.version.id === version.id ? <Check size={12} /> : null}</span>
                              {version.version_label}
                              {version.status === "active" ? <em>{t("labelActive")}</em> : <small>{t("referenceHistoricalVersion")}</small>}
                            </button>
                          ))}
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </div>
            <aside className="reference-selection-tray">
              <div><strong>{t("referenceSelectedDocuments")}</strong><small>{format("referenceSelectedCount", { count: selectedItems.length })}</small></div>
              {selectedItems.length ? selectedItems.map((item) => (
                <article key={selectionKey(item.project.id, item.document.id)}>
                  <span><strong>{item.document.title}</strong><small>{item.project.name} · {item.version.version_label}</small></span>
                  <button aria-label={format("referenceRemoveDocument", { title: item.document.title })} onClick={() => setSelections((current) => { const next = { ...current }; delete next[selectionKey(item.project.id, item.document.id)]; return next; })} type="button"><Trash2 size={14} /></button>
                  {item.version.status !== "active" ? <em><AlertTriangle size={12} /> {t("referenceOldVersion")}</em> : null}
                </article>
              )) : <p>{t("referenceNoSelection")}</p>}
            </aside>
          </div>
        ) : null}
        {oldRiskOpen ? <div className="reference-old-warning"><AlertTriangle size={18} /><span><strong>{t("referenceOldWarningTitle")}</strong><small>{t("referenceOldWarningHelp")}</small></span></div> : null}
        {submitErrors.length ? <div className="reference-old-warning error"><AlertTriangle size={18} /><span><strong>{t("referenceCreateFailed")}</strong><small>{submitErrors.map(localize).join(" · ")}</small></span></div> : null}
        <div className="modal-actions">
          <button className="action-button secondary" disabled={submitting} onClick={onClose} type="button">{t("cancel")}</button>
          <button className="action-button" disabled={!selectedItems.length || submitting || (mode === "reference" && selectedItems.length !== 1)} onClick={() => { void execute(); }} type="button">
            {submitting ? t("projectImportSubmitting") : oldRiskOpen ? t("referenceConfirmOldRisk") : mode === "copy" ? format("referenceCopyExtraction", { count: selectedItems.length }) : t("referenceConfirmStart")}
          </button>
        </div>
      </section>
    </div>
  );
}
