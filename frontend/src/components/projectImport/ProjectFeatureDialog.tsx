"use client";

import dynamic from "next/dynamic";
import type { RefObject } from "react";
import { X } from "lucide-react";
import { ProjectChatTest } from "@/components/ProjectChatTest";
import type { ImportPageDeps } from "./pageDeps";

// OPT424-036: the graph engine loads only when a graph dialog opens.
const ProjectGraphPreview = dynamic(() => import("@/components/ProjectGraphPreview").then(module => module.ProjectGraphPreview), { ssr: false });

type ProjectFeatureDialogProps = Pick<ImportPageDeps, "t"> & {
  activeModal: "graph" | "chat";
  dialogRef: RefObject<HTMLElement | null>;
  fixedChatVersion: string | undefined;
  onClose: () => void;
  projectId: string;
};

/** Knowledge graph and chat test dialog for the project import page (OPT424-038). */
export function ProjectFeatureDialog({ activeModal, dialogRef, fixedChatVersion, onClose, projectId, t }: ProjectFeatureDialogProps) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section ref={dialogRef} tabIndex={-1} aria-labelledby="project-feature-title" aria-modal="true" className={`modal-panel project-feature-modal ${activeModal === "chat" ? "project-chat-modal" : "project-graph-modal"}`} role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{t("projectImportFeatureEyebrow")}</p>
            <h2 id="project-feature-title">{activeModal === "graph" ? t("knowledgeGraph") : t("chatTest")}</h2>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label={t("projectImportCloseFeatureModal")}>
            <X size={18} />
          </button>
        </div>

        {activeModal === "graph" ? (
          <div className="feature-summary">
            <div className="feature-copy">
              <strong>{t("projectImportGraphHelpTitle")}</strong>
              <small>{t("projectImportGraphHelpDescription")}</small>
            </div>
            <ProjectGraphPreview />
          </div>
        ) : (
          <ProjectChatTest fixedVersionId={fixedChatVersion} key={`${projectId}:${fixedChatVersion ?? "all"}`} />
        )}
      </section>
    </div>
  );
}
