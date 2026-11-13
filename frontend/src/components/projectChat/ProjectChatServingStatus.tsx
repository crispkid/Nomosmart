"use client";

import type { Dispatch, SetStateAction } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ProjectServingStatusResponse } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";

type ProjectChatServingStatusProps = {
  servingExpanded: boolean;
  servingReadinessLabel: string;
  servingStatus: ProjectServingStatusResponse | null;
  setServingExpanded: Dispatch<SetStateAction<boolean>>;
};

/** Collapsible serving readiness summary for the project chat sidebar (OPT424-038). */
export function ProjectChatServingStatus({ servingExpanded, servingReadinessLabel, servingStatus, setServingExpanded }: ProjectChatServingStatusProps) {
  const { t, format } = useI18n();
  return (
    <section className={`project-serving-status readiness-${servingStatus?.readiness ?? "loading"}`} aria-label={t("projectChatServingStatus")}>
      <button aria-expanded={servingExpanded} className="project-serving-toggle" onClick={() => setServingExpanded((current) => !current)} type="button">
        <span><strong>{servingReadinessLabel}</strong><small>{format("projectChatServingSummary", { active: servingStatus?.active_document_count ?? 0, index: servingStatus?.ready_index_count ?? 0, graph: servingStatus?.graph_ready_count ?? 0 })}</small></span>
        {servingExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
      {servingExpanded ? (
        <div className="project-serving-documents">
          {(servingStatus?.documents ?? []).slice(0, 3).map((document) => (
            <span key={document.document_version_id}>{document.document_title} · {document.version_label} · {format("projectChatPublicationGeneration", { generation: document.publication_generation })} · {document.index_ready ? t("projectChatIndexReady") : t("projectChatIndexNotReady")} · {document.graph_sync_status ?? t("projectChatGraphUnknown")}</span>
          ))}
          {servingStatus && servingStatus.documents.length > 3 ? <span>{format("projectChatServingMore", { count: servingStatus.documents.length - 3 })}</span> : null}
        </div>
      ) : null}
    </section>
  );
}
