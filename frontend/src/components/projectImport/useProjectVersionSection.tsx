"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { CheckCircle2, Clock3, FolderSync, Layers3, ListRestart, RotateCcw, UploadCloud, X } from "lucide-react";
import { StatusBadge } from "@/components/AppShell";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import type { CreatedKnowledgeDocument } from "@/components/KnowledgeSourceModals";
import { ReferenceVersionSelect } from "@/components/ReferenceVersionSelect";
import { getPipelineDetail, listDataSourceSyncRuns, listProjectDocuments, listProjectReferenceSources, switchActiveDocumentVersion, updateDocumentReferenceVersion, updateProjectDocumentFile, type DataSyncRunResponse, type DocumentSummary, type ReferenceSourceVersionResponse } from "@/lib/api";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import type { useDocumentList } from "@/lib/useDocumentList";
import { formatSyncDate, getReferenceSource, getSourceState, isServiceDocument, isWorkingVersion, liveDocumentFromSummary, normalizeVersion, syncRunLabel, syncRunStep, type DocumentItem, type VersionSwitchTarget } from "./importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type DocumentList = ReturnType<typeof useDocumentList>;
type ProjectVersionStateDeps = Pick<ImportPageDeps, "apiFetch" | "format" | "params" | "t"> & {
  allDocuments: DocumentList["allDocuments"];
  syncRunsByDataSource: Record<string, DataSyncRunResponse[]>;
  setSyncRunsByDataSource: Dispatch<SetStateAction<Record<string, DataSyncRunResponse[]>>>;
  setSyncRunLoading: Dispatch<SetStateAction<Record<string, boolean>>>;
};
/** Page dependencies shared with the document version actions. */
export type ProjectVersionDeps = Pick<ImportPageDeps, "apiFetch" | "format" | "params" | "t"> & Pick<DocumentList, "replaceLiveDocuments" | "setCreatedImports" | "setLiveDocuments"> & {
  projectReady: boolean;
  canEditLifecycle: boolean;
};
type ProjectVersionViewDeps = Pick<ImportPageDeps, "format" | "locale" | "t"> & {
  canEditLifecycle: boolean;
  localize: (message: string) => string;
  syncRunLoading: Record<string, boolean>;
  refreshDataSourceSyncRuns: (dataSourceId: string) => Promise<DataSyncRunResponse[]>;
  syncNow: (document: DocumentItem) => Promise<void>;
};

export type ProjectVersionState = ReturnType<typeof useProjectVersionState>;

/** Document version, reference update and active-version switch state (split from the project import page, OPT424-038). */
export function useProjectVersionState(deps: ProjectVersionStateDeps) {
  const { apiFetch, format, params, t, allDocuments, syncRunsByDataSource, setSyncRunsByDataSource, setSyncRunLoading } = deps;
  const [versionDocumentId, setVersionDocumentId] = useState<string | null>(null);
  const updateFileInputRef = useRef<HTMLInputElement>(null);
  const [versionUpdateBusy, setVersionUpdateBusy] = useState(false);
  const [versionUpdateError, setVersionUpdateError] = useState("");
  const [versionUpdateNotice, setVersionUpdateNotice] = useState("");
  const [versionSwitchTarget, setVersionSwitchTarget] = useState<VersionSwitchTarget | null>(null);
  const [versionSwitchReason, setVersionSwitchReason] = useState("");
  const [versionSwitchBusy, setVersionSwitchBusy] = useState(false);
  const [versionSwitchError, setVersionSwitchError] = useState("");
  const [referenceUpdateVersions, setReferenceUpdateVersions] = useState<ReferenceSourceVersionResponse[]>([]);
  const [referenceUpdateVersionId, setReferenceUpdateVersionId] = useState("");
  const [referenceUpdateOldConfirmed, setReferenceUpdateOldConfirmed] = useState(false);
  const [referenceUpdateLoading, setReferenceUpdateLoading] = useState(false);
  const versionDocument = allDocuments.find((document) => document.id === versionDocumentId);
  const versionReferenceSource = versionDocument ? getReferenceSource(versionDocument) : null;
  const displayedVersions = versionDocument ? versionDocument.versions : [];
  const versionDataSourceId = versionDocument && "dataSourceId" in versionDocument ? versionDocument.dataSourceId : undefined;
  const currentSyncRuns = versionDataSourceId ? syncRunsByDataSource[versionDataSourceId] ?? [] : [];

  useEffect(() => {
    if (!versionDataSourceId) return;
    let cancelled = false;
    setSyncRunLoading((current) => ({ ...current, [versionDataSourceId]: true }));
    listDataSourceSyncRuns(apiFetch, params.id, versionDataSourceId)
      .then((runs) => {
        if (!cancelled) setSyncRunsByDataSource((current) => ({ ...current, [versionDataSourceId]: runs }));
      })
      .catch(() => {
        if (!cancelled) setSyncRunsByDataSource((current) => ({ ...current, [versionDataSourceId]: [] }));
      })
      .finally(() => {
        if (!cancelled) setSyncRunLoading((current) => ({ ...current, [versionDataSourceId]: false }));
      });
    return () => {
      cancelled = true;
    };
  }, [apiFetch, params.id, setSyncRunLoading, setSyncRunsByDataSource, versionDataSourceId]);

  useEffect(() => {
    const source = versionReferenceSource;
    // Opening another document resets the reference update form before loading its versions.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    setReferenceUpdateVersions([]);
    setReferenceUpdateVersionId("");
    setReferenceUpdateOldConfirmed(false);
    if (!source?.referenceId || !source.sourceDocumentId || !source.hasAccess) return;
    let cancelled = false;
    setReferenceUpdateLoading(true);
    listProjectReferenceSources(apiFetch, params.id)
      .then((projects) => {
        if (cancelled) return;
        const documents = projects.flatMap((project) => project.documents);
        const sourceDocument = documents.find((document) => document.id === source.sourceDocumentId);
        const versions = sourceDocument?.versions ?? [];
        setReferenceUpdateVersions(versions);
        const selected = versions.find((version) => version.id === source.sourceVersionId) ?? versions.find((version) => version.status === "active") ?? versions[0];
        setReferenceUpdateVersionId(selected?.id ?? "");
      })
      .catch((error) => {
        if (!cancelled) setVersionUpdateError(operationalErrorMessage(error, t, format, "referenceLoadSourcesFailed"));
      })
      .finally(() => {
        if (!cancelled) setReferenceUpdateLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiFetch, format, params.id, t, versionReferenceSource]);
  return { versionDocumentId, setVersionDocumentId, updateFileInputRef, versionUpdateBusy, setVersionUpdateBusy, versionUpdateError, setVersionUpdateError, versionUpdateNotice, setVersionUpdateNotice, versionSwitchTarget, setVersionSwitchTarget, versionSwitchReason, setVersionSwitchReason, versionSwitchBusy, setVersionSwitchBusy, versionSwitchError, setVersionSwitchError, referenceUpdateVersions, setReferenceUpdateVersions, referenceUpdateVersionId, setReferenceUpdateVersionId, referenceUpdateOldConfirmed, setReferenceUpdateOldConfirmed, referenceUpdateLoading, setReferenceUpdateLoading, versionDocument, versionReferenceSource, displayedVersions, versionDataSourceId, currentSyncRuns };
}

/** Document version actions, created each render once page dependencies exist. */
export function createProjectVersionActions(state: ProjectVersionState, deps: ProjectVersionDeps) {
  const { apiFetch, format, params, t, projectReady, canEditLifecycle, replaceLiveDocuments, setCreatedImports, setLiveDocuments } = deps;
  const { setVersionDocumentId, updateFileInputRef, versionUpdateBusy, setVersionUpdateBusy, setVersionUpdateError, setVersionUpdateNotice, versionSwitchTarget, setVersionSwitchTarget, versionSwitchReason, setVersionSwitchReason, versionSwitchBusy, setVersionSwitchBusy, setVersionSwitchError, referenceUpdateVersions, referenceUpdateVersionId, referenceUpdateOldConfirmed, setReferenceUpdateOldConfirmed, versionDocument, versionReferenceSource } = state;

  async function hydrateUpdatedDocument(document: DocumentSummary) {
    const versionId = document.latest_version?.id;
    const pipelineId = document.latest_pipeline?.id;
    if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
    try {
      const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId);
      return liveDocumentFromSummary(document, t, detail);
    } catch {
      return liveDocumentFromSummary(document, t);
    }
  }

  async function reloadLiveDocuments() {
    const documents = await listProjectDocuments(apiFetch, params.id);
    const hydrated = await Promise.all(documents.map((document) => hydrateUpdatedDocument(document)));
    replaceLiveDocuments(hydrated);
    return hydrated;
  }

  async function applyUpdatedDocument(document: DocumentSummary) {
    const next = await hydrateUpdatedDocument(document);
    setLiveDocuments((current) => current.map((item) => item.id === next.id ? next : item));
    setCreatedImports((current) => current.map((item) => item.id === next.id ? next : item));
    return next;
  }

  async function updateCurrentFileVersion(file: File | null | undefined) {
    if (!projectReady || !file || !versionDocument?.isLive || versionUpdateBusy) return;
    setVersionUpdateBusy(true);
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      const response = await updateProjectDocumentFile(apiFetch, params.id, versionDocument.id, file);
      if (response.no_change) {
        setVersionUpdateNotice(t("projectImportUpdateNoChange"));
        return;
      }
      const next = await applyUpdatedDocument(response.document);
      setVersionDocumentId(next.id);
      setVersionUpdateNotice(t("projectImportUpdateStarted"));
    } catch (error) {
      setVersionUpdateError(operationalErrorMessage(error, t, format, "projectImportUpdateFailed"));
    } finally {
      setVersionUpdateBusy(false);
      if (updateFileInputRef.current) updateFileInputRef.current.value = "";
    }
  }

  async function updateCurrentReferenceVersion() {
    const source = versionReferenceSource;
    if (!projectReady || !source?.referenceId || !referenceUpdateVersionId || versionUpdateBusy) return;
    const selected = referenceUpdateVersions.find((version) => version.id === referenceUpdateVersionId);
    if (selected && selected.status !== "active" && !referenceUpdateOldConfirmed) {
      setVersionUpdateError(t("projectImportReferenceOldVersionConfirmRequired"));
      return;
    }
    setVersionUpdateBusy(true);
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      const response = await updateDocumentReferenceVersion(apiFetch, source.referenceId, { source_version_id: referenceUpdateVersionId, old_version_confirmed: referenceUpdateOldConfirmed });
      const next = await applyUpdatedDocument(response.document);
      setVersionDocumentId(next.id);
      setVersionUpdateNotice(response.no_change ? t("projectImportReferenceNoChange") : t("projectImportReferenceUpdateStarted"));
      setReferenceUpdateOldConfirmed(false);
    } catch (error) {
      setVersionUpdateError(operationalErrorMessage(error, t, format, "projectImportUpdateFailed"));
    } finally {
      setVersionUpdateBusy(false);
    }
  }

  function requestVersionSwitch(version: CreatedKnowledgeDocument["versions"][number]) {
    if (!versionDocument || version.status !== "inactive" || !canEditLifecycle) return;
    setVersionSwitchTarget({ document: versionDocument, version });
    setVersionSwitchReason(format("projectImportSwitchActiveDefaultReason", { version: version.label }));
    setVersionSwitchError("");
  }

  async function confirmVersionSwitch() {
    if (!canEditLifecycle || !versionSwitchTarget || versionSwitchBusy) return;
    const target = versionSwitchTarget;
    const reason = versionSwitchReason.trim();
    if (!reason) {
      setVersionSwitchError(t("projectImportSwitchActiveReasonRequired"));
      return;
    }
    if (!target.version.lockVersion) {
      setVersionSwitchError(t("projectImportMissingLockVersion"));
      return;
    }
    setVersionSwitchBusy(true);
    setVersionSwitchError("");
    setVersionUpdateError("");
    setVersionUpdateNotice("");
    try {
      await switchActiveDocumentVersion(apiFetch, target.version.id, {
        lock_version: target.version.lockVersion,
        impact_confirmed: true,
        audit_reason: reason
      });
      const refreshed = await reloadLiveDocuments();
      setCreatedImports((current) => current.filter((item) => !refreshed.some((document) => document.id === item.id)));
      setVersionDocumentId(target.document.id);
      setVersionSwitchTarget(null);
      setVersionSwitchReason("");
      setVersionUpdateNotice(format("projectImportVersionSwitchSuccess", { version: target.version.label }));
    } catch (error) {
      setVersionSwitchError(operationalErrorMessage(error, t, format, "projectImportVersionSwitchFailed"));
    } finally {
      setVersionSwitchBusy(false);
    }
  }

  return { updateCurrentFileVersion, updateCurrentReferenceVersion, requestVersionSwitch, confirmVersionSwitch };
}

export type ProjectVersionActions = ReturnType<typeof createProjectVersionActions>;

/** Document version dialogs: JSX moved verbatim from the project import page (OPT424-038). */
export function createProjectVersionView(state: ProjectVersionState, actions: ProjectVersionActions, deps: ProjectVersionViewDeps) {
  const { setVersionDocumentId, updateFileInputRef, versionUpdateBusy, versionUpdateError, versionUpdateNotice, versionSwitchTarget, setVersionSwitchTarget, versionSwitchReason, setVersionSwitchReason, versionSwitchBusy, versionSwitchError, referenceUpdateVersions, referenceUpdateVersionId, setReferenceUpdateVersionId, referenceUpdateOldConfirmed, setReferenceUpdateOldConfirmed, referenceUpdateLoading, versionDocument, versionReferenceSource, displayedVersions, versionDataSourceId, currentSyncRuns } = state;
  const { updateCurrentFileVersion, updateCurrentReferenceVersion, requestVersionSwitch, confirmVersionSwitch } = actions;

  function renderProjectVersionModals() {
    const { canEditLifecycle, format, locale, localize, syncRunLoading, refreshDataSourceSyncRuns, syncNow, t } = deps;
    return (
      <>
      {versionDocument ? (
        <div className="modal-backdrop" role="presentation">
          <section aria-modal="true" className="modal-panel version-modal" role="dialog">
            <div className="modal-header">
              <div>
                <p className="eyebrow">{versionDocument.title}</p>
                <h2>{t("projectImportVersionManagement")}</h2>
              </div>
              <button className="icon-button" onClick={() => setVersionDocumentId(null)} type="button" aria-label={t("projectImportCloseVersionModal")}>
                <X size={18} />
              </button>
            </div>
            <div className="current-version-card">
              <div className="current-version-primary">
                <span>{t("projectImportCurrentVersion")}</span>
                <strong>{normalizeVersion(versionDocument.version)}</strong>
                <StatusBadge status={versionDocument.versionStatus} />
              </div>
              <div className="current-version-roles">
                {versionDocument.versions.find((version) => version.status === "active") ? <span className="version-role-active"><CheckCircle2 size={14} /> {t("statusActive")}：{versionDocument.versions.find((version) => version.status === "active")?.label}</span> : null}
                {versionDocument.versions.find((version) => isWorkingVersion(version.status)) ? <span className="version-role-working"><Clock3 size={14} /> {t("projectImportWorkingVersion")}：{versionDocument.versions.find((version) => isWorkingVersion(version.status))?.label}</span> : null}
              </div>
            </div>
            {versionUpdateNotice ? <div className="reference-result compact"><CheckCircle2 size={18} /><span><strong>{localize(versionUpdateNotice)}</strong></span></div> : null}
            {versionUpdateError ? <FeedbackMessage tone="error"><strong>{localize(versionUpdateError)}</strong></FeedbackMessage> : null}
            {versionDocument.sourceType === "File upload" ? (
              <div className="version-update-action">
                <div><strong>{t("projectImportUpdateDocument")}</strong><small>{t("projectImportUpdateDocumentHelp")}</small></div>
                <input
                  ref={updateFileInputRef}
                  className="sr-only"
                  onChange={(event) => { void updateCurrentFileVersion(event.target.files?.[0]); }}
                  type="file"
                />
                <button className="action-button secondary" disabled={versionUpdateBusy} onClick={() => updateFileInputRef.current?.click()} type="button">
                  <UploadCloud size={16} /> {versionUpdateBusy ? t("projectImportSubmitting") : t("projectImportChooseUpdateFile")}
                </button>
              </div>
            ) : null}
            {isServiceDocument(versionDocument) ? <div className="version-sync-action"><div><FolderSync size={18} /><span><strong>{t("projectImportDataServiceSync")}</strong><small>{t("projectImportDataServiceSyncHelp")}</small></span></div><button className="action-button secondary" disabled={getSourceState(versionDocument) === "syncing"} onClick={() => syncNow(versionDocument)} type="button"><FolderSync size={16} /> {getSourceState(versionDocument) === "syncing" ? t("projectImportSyncingEllipsis") : t("syncNow")}</button></div> : null}
            {"serviceSource" in versionDocument && versionDocument.serviceSource ? <div className="service-refresh-detail"><span>{t("projectImportServiceSource")}：{versionDocument.serviceSource.serviceType}</span><span>{t("projectImportServiceLocation")}：{versionDocument.serviceSource.location}</span><span>{t("projectImportServiceSchedule")}：{versionDocument.serviceSource.scheduleMode === "cron" ? `${versionDocument.serviceSource.cronExpression} · ${versionDocument.serviceSource.timezone}` : t("projectImportOneTime")}</span></div> : null}
            {versionDataSourceId ? (
              <>
                <div className="version-list-heading">
                  <strong>{t("projectImportSyncHistory")}</strong>
                  <button className="text-link" disabled={syncRunLoading[versionDataSourceId]} onClick={() => { void refreshDataSourceSyncRuns(versionDataSourceId); }} type="button">
                    <RotateCcw size={15} /> {syncRunLoading[versionDataSourceId] ? t("projectImportRefreshing") : t("projectImportRefresh")}
                  </button>
                </div>
                <div className="version-list">
                  {currentSyncRuns.length > 0 ? currentSyncRuns.slice(0, 5).map((run) => (
                    <article className="version-row" key={run.id}>
                      <div>
                        <strong>{syncRunLabel(run.status, t)} · {run.trigger_type === "scheduled" ? t("projectImportScheduled") : t("projectImportManual")}</strong>
                        <small>{syncRunStep(run, t)} · {formatSyncDate(run.completed_at ?? run.started_at ?? run.created_at, locale)}</small>
                      </div>
                      <StatusBadge status={run.status === "success" || run.status === "unchanged" ? "completed" : run.status === "failed" ? "failed" : "running"} />
                    </article>
                  )) : (
                    <div className="empty-state">{syncRunLoading[versionDataSourceId] ? t("projectImportLoadingSyncRuns") : t("projectImportNoSyncRuns")}</div>
                  )}
                </div>
              </>
            ) : null}
            {versionReferenceSource ? (
              <div className="reference-source-detail">
                <div className="reference-source-heading"><Layers3 size={17} /><span><strong>{t("projectImportReferenceSource")}</strong><small>{versionReferenceSource.hasAccess ? t("projectImportReferenceSourceAccessible") : t("projectImportReferenceSourceSnapshot")}</small></span></div>
                <dl><div><dt>{t("projectImportReferenceProject")}</dt><dd>{versionReferenceSource.projectName}</dd></div><div><dt>{t("projectImportReferenceDocument")}</dt><dd>{versionReferenceSource.documentName}</dd></div><div><dt>{t("projectImportCurrentReferenceVersion")}</dt><dd>{versionReferenceSource.snapshotVersion}</dd></div><div><dt>{t("projectImportLatestActive")}</dt><dd>{versionReferenceSource.latestActiveVersion}</dd></div><div><dt>{t("projectImportReferenceEvents")}</dt><dd>{versionReferenceSource.pendingEventCount ?? 0}</dd></div></dl>
              </div>
            ) : null}
            {versionReferenceSource?.referenceId ? (
              <div className="version-sync-action">
                <div><Layers3 size={18} /><span><strong>{t("projectImportReferenceUpdateVersion")}</strong><small>{t("projectImportReferenceUpdateVersionHelp")}</small></span></div>
                <div className="version-reference-update-controls">
                  <ReferenceVersionSelect documentTitle={versionDocument.title} disabled={!versionReferenceSource.hasAccess || referenceUpdateLoading || versionUpdateBusy} loading={referenceUpdateLoading} value={referenceUpdateVersionId} versions={referenceUpdateVersions} description={[
                    format("referenceVersionCurrentSnapshot", { version: versionReferenceSource.snapshotVersion }),
                    !versionReferenceSource.hasAccess ? t("referenceVersionNoAccess") : referenceUpdateLoading ? t("loadingData") : versionUpdateBusy ? t("referenceVersionUpdating") : t("projectImportReferenceUpdateVersionHelp")
                  ].join(" ")} onChange={value => { setReferenceUpdateVersionId(value); setReferenceUpdateOldConfirmed(false); }} />
                  {referenceUpdateVersions.find((version) => version.id === referenceUpdateVersionId)?.status !== "active" && referenceUpdateVersionId ? (
                    <label className="field-note reference-old-confirm">
                      <input checked={referenceUpdateOldConfirmed} onChange={(event) => setReferenceUpdateOldConfirmed(event.target.checked)} type="checkbox" />
                      {t("projectImportReferenceOldVersionConfirm")}
                    </label>
                  ) : null}
                  <button className="action-button secondary" disabled={!versionReferenceSource.hasAccess || !referenceUpdateVersionId || versionUpdateBusy} onClick={() => { void updateCurrentReferenceVersion(); }} type="button"><RotateCcw size={16} /> {versionUpdateBusy ? t("projectImportSubmitting") : t("projectImportUpdateReference")}</button>
                </div>
              </div>
            ) : null}
            {versionReferenceSource?.pendingEventCount ? <FeedbackMessage tone="warning"><span><strong>{format("projectImportReferencePendingEvents", { count: versionReferenceSource.pendingEventCount })}</strong><small>{t("projectImportReferencePendingEventsHelp")}</small></span></FeedbackMessage> : null}
            {versionReferenceSource && !versionReferenceSource.pendingEventCount && versionReferenceSource.latestActiveVersion !== versionReferenceSource.snapshotVersion ? <FeedbackMessage tone="warning"><span><strong>{t("projectImportReferenceNewVersionTitle")}</strong><small>{format("projectImportReferenceNewVersionHelp", { snapshot: versionReferenceSource.snapshotVersion, latest: versionReferenceSource.latestActiveVersion })}</small></span></FeedbackMessage> : null}
            <div className="version-list-heading"><strong>{t("projectImportVersionHistory")}</strong><small>{t("projectImportVersionHistoryHelp")}</small></div>
            <div className="version-list">
              {displayedVersions.map((version) => {
                const activeVersion = version.status === "active";
                const switchableVersion = version.status === "inactive";
                const canSwitchVersion = canEditLifecycle && switchableVersion;
                return (
                  <article className="version-row" key={version.id}>
                    <div>
                      <strong>{version.label}</strong>
                      <small>{version.createdAt} · {version.author}</small>
                    </div>
                    <StatusBadge status={version.status} />
                    <button
                      className="action-button secondary"
                      disabled={!canSwitchVersion || versionSwitchBusy}
                      onClick={() => requestVersionSwitch(version)}
                      title={!canEditLifecycle ? t("projectImportMissingLifecyclePermission") : !switchableVersion && !activeVersion ? t("projectImportVersionSwitchBlocked") : undefined}
                      type="button"
                    >
                      {activeVersion ? t("projectImportCurrentVersionBadge") : canSwitchVersion ? t("projectImportSwitchActiveVersion") : t("projectImportVersionSwitchBlocked")}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      ) : null}

      {versionSwitchTarget ? (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !versionSwitchBusy) setVersionSwitchTarget(null);
          }}
          role="presentation"
        >
          <section aria-labelledby="version-switch-title" aria-modal="true" className="modal-panel warning-modal" role="alertdialog">
            <div className="modal-header">
              <div><p className="eyebrow">{versionSwitchTarget.document.title}</p><h2 id="version-switch-title">{t("projectImportSwitchActiveTitle")}</h2></div>
              <button aria-label={t("projectImportCloseVersionSwitchWarning")} className="icon-button" disabled={versionSwitchBusy} onClick={() => setVersionSwitchTarget(null)} type="button"><X size={18} /></button>
            </div>
            <div className="warning-body"><ListRestart size={24} /><div><strong>{versionSwitchTarget.version.label}</strong><small>{t("projectImportSwitchActiveHelp")}</small></div></div>
            {versionSwitchError ? <FeedbackMessage tone="error"> {localize(versionSwitchError)}</FeedbackMessage> : null}
            <label className="field-stack">
              <span>{t("projectImportSwitchActiveReason")}</span>
              <textarea disabled={versionSwitchBusy} onChange={(event) => setVersionSwitchReason(event.target.value)} value={versionSwitchReason} />
            </label>
            <div className="modal-actions">
              <button className="action-button secondary" disabled={versionSwitchBusy} onClick={() => setVersionSwitchTarget(null)} type="button">{t("cancel")}</button>
              <button className="action-button" disabled={versionSwitchBusy || !versionSwitchReason.trim()} onClick={() => { void confirmVersionSwitch(); }} type="button">{versionSwitchBusy ? t("projectImportSubmitting") : t("projectImportConfirmSwitchActive")}</button>
            </div>
          </section>
        </div>
      ) : null}
      </>
    );
  }

  return { renderProjectVersionModals };
}
