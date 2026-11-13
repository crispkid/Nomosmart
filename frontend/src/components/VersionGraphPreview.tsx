"use client";

import { useCallback } from "react";
import { useAuth } from "@/components/AuthProvider";
import { DocumentGraphPreview } from "@/components/DocumentGraphPreview";
import { getDocumentVersionGraph, type ProjectGraphResponse } from "@/lib/api";
import { versionGraphEvidence } from "@/lib/versionGraphEvidence";
import { useGraphSourceBinding } from "@/lib/useGraphSourceBinding";
import { useI18n } from "@/lib/i18nClient";
import { useReadResource } from "@/lib/useReadResource";

type GraphErrorKey = "graphProjectionNotReady" | "graphProjectForbiddenStatus" | "graphProjectUnavailableStatus";

function graphErrorKey(failure: { code?: string; status?: number } | undefined): GraphErrorKey {
  return failure?.code === "graph_projection_not_ready" || failure?.code === "graph_identity_conflict"
    ? "graphProjectionNotReady" : failure?.status === 403 ? "graphProjectForbiddenStatus" : "graphProjectUnavailableStatus";
}

/** Both draft and published dialogs follow the Backend's scoped evidence source. */
export function VersionGraphPreview({ projectId, documentId, versionId, documentTitle, version }: {
  projectId: string; documentId: string; versionId: string; documentTitle: string; version: string;
}) {
  const { apiFetch, authReady } = useAuth();
  const { t, format } = useI18n();
  const scope = `${projectId}/${documentId}/${versionId}`;
  const readGraph = useCallback((signal: AbortSignal) => getDocumentVersionGraph(apiFetch, projectId, documentId, versionId, 500, signal), [apiFetch, projectId, documentId, versionId]);
  const graphRead = useReadResource<ProjectGraphResponse>(readGraph, scope, authReady);
  const graph = graphRead.data;
  const binding = useGraphSourceBinding(graph);
  const error = graphRead.status === "error" ? graphErrorKey(graphRead.error as { code?: string; status?: number }) : null;
  if (!graph) return <p role="status">{t(error ?? "graphProjectLoadingStatus")}</p>;
  const evidence = versionGraphEvidence(graph, versionId, documentTitle);
  return <>
    {graph.truncated ? <p role="status">{format("graphVersionTruncatedStatus", { limit: graph.node_limit })}</p> : null}
    <DocumentGraphPreview layoutScope={scope} layoutBinding={binding} documentTitle={documentTitle} version={version} documentTags={evidence.documentTags} graphChunks={evidence.chunks} />
  </>;
}
