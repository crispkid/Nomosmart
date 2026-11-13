"use client";

import { useState } from "react";
import type { CreatedKnowledgeDocument, SourceState } from "@/components/KnowledgeSourceModals";
import { listDataSourceSyncRuns, queueDataSourceSync, type DataSyncRunResponse } from "@/lib/api";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";
import type { useDocumentList } from "@/lib/useDocumentList";
import { formatSyncDate, syncRunStep, type DocumentItem } from "./importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type DocumentList = ReturnType<typeof useDocumentList>;
/** Page dependencies shared with the data source sync actions. */
export type DataSourceSyncDeps = Pick<ImportPageDeps, "apiFetch" | "format" | "locale" | "params" | "t"> & Pick<DocumentList, "setCreatedImports" | "setLiveDocuments"> & {
  projectReady: boolean;
};

export type DataSourceSyncState = ReturnType<typeof useDataSourceSyncState>;

/** Data source sync run state (split from the project import page, OPT424-038). */
export function useDataSourceSyncState() {
  const [syncRunsByDataSource, setSyncRunsByDataSource] = useState<Record<string, DataSyncRunResponse[]>>({});
  const [syncRunLoading, setSyncRunLoading] = useState<Record<string, boolean>>({});
  return { syncRunsByDataSource, setSyncRunsByDataSource, syncRunLoading, setSyncRunLoading };
}

/** Data source sync actions, created each render once page dependencies exist. */
export function createDataSourceSyncActions(state: DataSourceSyncState, deps: DataSourceSyncDeps) {
  const { apiFetch, format, locale, params, t, projectReady, setCreatedImports, setLiveDocuments } = deps;
  const { setSyncRunsByDataSource, setSyncRunLoading } = state;

  async function refreshDataSourceSyncRuns(dataSourceId: string) {
    setSyncRunLoading((current) => ({ ...current, [dataSourceId]: true }));
    try {
      const runs = await listDataSourceSyncRuns(apiFetch, params.id, dataSourceId);
      setSyncRunsByDataSource((current) => ({ ...current, [dataSourceId]: runs }));
      return runs;
    } finally {
      setSyncRunLoading((current) => ({ ...current, [dataSourceId]: false }));
    }
  }

  function applySyncRunState(documentId: string, run: DataSyncRunResponse) {
    const sourceState: SourceState = run.status === "failed" ? "sync_failed" : run.status === "success" || run.status === "unchanged" ? "ready_for_extraction" : "syncing";
    const syncedAt = formatSyncDate(run.completed_at ?? run.started_at ?? run.created_at, locale);
    const patch = {
      sourceState,
      updatedAt: syncedAt,
      pipeline: {
        currentStep: syncRunStep(run, t),
        elapsed: "",
        eta: run.status === "queued" ? t("projectImportWaitingWorker") : run.status === "running" ? t("projectImportSyncRunning") : "",
        error: run.error_summary ? operationalCodeMessage(run.error_code, t, format, "projectImportSyncFailed") : ""
      }
    };
    const applyPatch = (item: CreatedKnowledgeDocument): CreatedKnowledgeDocument => {
      if (item.id !== documentId) return item;
      const nextVersions = run.document_version_id && !item.versions.some((version) => version.id === run.document_version_id)
        ? [{ id: run.document_version_id, label: t("projectImportLatestSyncVersion"), status: "draft", createdAt: syncedAt, author: t("projectImportSystemSync") }, ...item.versions]
        : item.versions;
      return {
        ...item,
        ...patch,
        latestVersionId: run.document_version_id ?? item.latestVersionId,
        versionStatus: run.document_version_id ? "draft" : item.versionStatus,
        versions: nextVersions,
        pipeline: { ...item.pipeline, ...patch.pipeline }
      };
    };
    setCreatedImports((current) => current.map(applyPatch));
    setLiveDocuments((current) => current.map(applyPatch));
  }

  async function pollDataSourceSyncRun(documentId: string, dataSourceId: string, runId: string) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, attempt === 0 ? 500 : 2000));
      const runs = await refreshDataSourceSyncRuns(dataSourceId);
      const latestRun = runs.find((run) => run.id === runId) ?? runs[0];
      if (!latestRun) continue;
      applySyncRunState(documentId, latestRun);
      if (["success", "unchanged", "failed"].includes(latestRun.status)) return;
    }
  }

  async function syncNow(document: DocumentItem) {
    if (!projectReady) return;
    if ("dataSourceId" in document && document.dataSourceId) {
      setCreatedImports((current) => current.map((item) => item.id === document.id ? {
        ...item,
        sourceState: "syncing",
        pipeline: { ...item.pipeline, currentStep: t("projectImportManualSyncSource"), elapsed: "00m 01s", eta: t("projectImportWaitingWorker"), error: "" }
      } : item));
      try {
        const run = await queueDataSourceSync(apiFetch, params.id, document.dataSourceId);
        setSyncRunsByDataSource((current) => ({ ...current, [document.dataSourceId!]: [run, ...(current[document.dataSourceId!] ?? []).filter((item) => item.id !== run.id)] }));
        applySyncRunState(document.id, run);
        void pollDataSourceSyncRun(document.id, document.dataSourceId, run.id);
      } catch (error) {
        setCreatedImports((current) => current.map((item) => item.id === document.id ? {
          ...item,
          sourceState: "sync_failed",
          pipeline: { ...item.pipeline, currentStep: t("projectImportSyncScheduleFailed"), elapsed: "", eta: "", error: operationalErrorMessage(error, t, format, "projectImportSyncScheduleFailed") }
        } : item));
      }
      return;
    }
    setCreatedImports((current) => current.map((item) => item.id === document.id ? {
      ...item,
      sourceState: "syncing",
      pipeline: { ...item.pipeline, currentStep: t("projectImportManualSyncSource"), elapsed: "00m 01s", eta: t("projectImportWaitingRemoteService") }
    } : item));
  }

  return { refreshDataSourceSyncRuns, syncNow };
}
