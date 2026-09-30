"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { DocumentGraphPreview } from "@/components/DocumentGraphPreview";
import { getDocumentVersionGraph, type ProjectGraphResponse } from "@/lib/api";
import { versionGraphEvidence } from "@/lib/versionGraphEvidence";
import { useI18n } from "@/lib/i18nClient";

type GraphErrorKey = "graphProjectionNotReady" | "graphProjectForbiddenStatus" | "graphProjectUnavailableStatus";

/** Both draft and published dialogs follow the Backend's scoped evidence source. */
export function VersionGraphPreview({ projectId, documentId, versionId, documentTitle, version }: {
  projectId: string; documentId: string; versionId: string; documentTitle: string; version: string;
}) {
  const { apiFetch, authReady } = useAuth();
  const { t, format } = useI18n();
  const scope = `${projectId}/${documentId}/${versionId}`;
  const [loaded, setLoaded] = useState<{ scope: string; graph: ProjectGraphResponse | null; error: GraphErrorKey | null } | null>(null);
  const graph = authReady && loaded?.scope === scope ? loaded.graph : null;
  const error = authReady && loaded?.scope === scope ? loaded.error : null;
  useEffect(() => {
    let cancelled = false;
    if (!authReady) return;
    getDocumentVersionGraph(apiFetch, projectId, documentId, versionId, 500)
      .then((result) => { if (!cancelled) setLoaded({ scope, graph: result, error: null }); })
      .catch((failure: { code?: string; status?: number }) => {
        if (!cancelled) setLoaded({ scope, graph: null, error: failure.code === "graph_projection_not_ready" || failure.code === "graph_identity_conflict"
          ? "graphProjectionNotReady" : failure.status === 403 ? "graphProjectForbiddenStatus" : "graphProjectUnavailableStatus" });
      });
    return () => { cancelled = true; };
  }, [apiFetch, authReady, projectId, documentId, versionId, scope]);
  if (!graph) return <p role="status">{t(error ?? "graphProjectLoadingStatus")}</p>;
  const evidence = versionGraphEvidence(graph, versionId, documentTitle);
  return <>
    {graph.truncated ? <p role="status">{format("graphVersionTruncatedStatus", { limit: graph.node_limit })}</p> : null}
    <DocumentGraphPreview documentTitle={documentTitle} version={version} documentTags={evidence.documentTags} graphChunks={evidence.chunks} />
  </>;
}
