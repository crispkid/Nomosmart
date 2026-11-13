"use client";

import { useState } from "react";
import { ProjectReferenceModal } from "@/components/ProjectReferenceModal";
import type { useDocumentList } from "@/lib/useDocumentList";
import { getPipelineDetail, importProjectDocumentReferences, listProjectReferenceSources, type ReferenceSourceProjectResponse } from "@/lib/api";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";
import { UiValidationError } from "@/lib/transportError";
import { liveDocumentFromSummary } from "./importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type DocumentList = ReturnType<typeof useDocumentList>;
/** Page dependencies shared with the cross-project reference actions. */
export type ReferenceSourceDeps = Pick<ImportPageDeps, "apiFetch" | "format" | "params" | "t"> & Pick<DocumentList, "setCreatedImports"> & {
  projectReady: boolean;
};

export type ReferenceSourceState = ReturnType<typeof useReferenceSourceState>;

/** Cross-project reference source state (split from the project import page, OPT424-038). */
export function useReferenceSourceState() {
  const [referenceModalOpen, setReferenceModalOpen] = useState(false);
  const [referenceSources, setReferenceSources] = useState<ReferenceSourceProjectResponse[]>([]);
  const [referenceSourcesLoading, setReferenceSourcesLoading] = useState(false);
  const [referenceSourcesError, setReferenceSourcesError] = useState("");
  return { referenceModalOpen, setReferenceModalOpen, referenceSources, setReferenceSources, referenceSourcesLoading, setReferenceSourcesLoading, referenceSourcesError, setReferenceSourcesError };
}

/** Cross-project reference actions, created each render once page dependencies exist. */
export function createReferenceSourceActions(state: ReferenceSourceState, deps: ReferenceSourceDeps) {
  const { apiFetch, format, params, t, projectReady, setCreatedImports } = deps;
  const { setReferenceModalOpen, setReferenceSources, setReferenceSourcesLoading, setReferenceSourcesError } = state;

  async function loadReferenceSources() {
    setReferenceModalOpen(true);
    setReferenceSourcesLoading(true);
    setReferenceSourcesError("");
    try {
      const sources = await listProjectReferenceSources(apiFetch, params.id);
      setReferenceSources(sources);
    } catch (error) {
      setReferenceSourcesError(operationalErrorMessage(error, t, format, "referenceLoadSourcesFailed"));
    } finally {
      setReferenceSourcesLoading(false);
    }
  }

  async function createLiveReferences(mode: "reference" | "copy", items: Array<{ source_document_id: string; source_version_id: string; old_version_confirmed?: boolean }>) {
    if (!projectReady) throw new UiValidationError("projectImportUploadNotAllowed");
    const response = await importProjectDocumentReferences(apiFetch, params.id, { mode, items });
    const created = await Promise.all(response.results.filter((result) => result.status === "created" && result.document).map(async (result) => {
      const document = result.document!;
      const versionId = document.latest_version?.id;
      const pipelineId = document.latest_pipeline?.id;
      if (!versionId || !pipelineId) return liveDocumentFromSummary(document, t);
      try {
        const detail = await getPipelineDetail(apiFetch, params.id, document.id, versionId, pipelineId);
        return liveDocumentFromSummary(document, t, detail);
      } catch {
        return liveDocumentFromSummary(document, t);
      }
    }));
    if (created.length) setCreatedImports((current) => [...created, ...current]);
    return {
      createdCount: created.length,
      errors: response.results.filter((result) => result.status === "failed").map((result) => operationalCodeMessage(result.error_code, t, format, "referenceCreateFailed"))
    };
  }

  return { loadReferenceSources, createLiveReferences };
}

export type ReferenceSourceActions = ReturnType<typeof createReferenceSourceActions>;

/** Cross-project reference dialog: JSX moved verbatim from the project import page (OPT424-038). */
export function createReferenceSourceView(state: ReferenceSourceState, actions: ReferenceSourceActions) {
  const { referenceModalOpen, setReferenceModalOpen, referenceSources, referenceSourcesLoading, referenceSourcesError } = state;
  const { loadReferenceSources, createLiveReferences } = actions;

  function renderReferenceModal() {
    return (
      <>
      {referenceModalOpen ? (
        <ProjectReferenceModal
          error={referenceSourcesError}
          loading={referenceSourcesLoading}
          onClose={() => setReferenceModalOpen(false)}
          onCreate={createLiveReferences}
          onRefresh={() => { void loadReferenceSources(); }}
          sources={referenceSources}
        />
      ) : null}
      </>
    );
  }

  return { renderReferenceModal };
}
