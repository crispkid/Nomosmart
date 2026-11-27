"use client";

import dynamic from "next/dynamic";
import { ProjectChatTest } from "@/components/ProjectChatTest";
import type { ImportPageDeps } from "./pageDeps";

// OPT424-036: the graph engine loads only when the graph tab opens.
const ProjectGraphPreview = dynamic(() => import("@/components/ProjectGraphPreview").then(module => module.ProjectGraphPreview), { ssr: false });

/** CHG-495 M13 (K081): the knowledge graph as a project page tab (it was a dialog before). */
export function ProjectGraphTab({ t }: Pick<ImportPageDeps, "t">) {
  return (
    <section aria-labelledby="project-graph-title" className="project-tab-panel project-graph-tab">
      <div className="project-tab-intro">
        <h2 id="project-graph-title">{t("knowledgeGraph")}</h2>
        <p>{t("projectImportGraphHelpTitle")} {t("projectImportGraphHelpDescription")}</p>
      </div>
      <div className="feature-summary">
        <ProjectGraphPreview />
      </div>
    </section>
  );
}

/** CHG-495 M13 (K082, S10): the chat test as a project page tab; `?chat_version_id` fixes its document scope. */
export function ProjectChatTab({ fixedChatVersion, projectId, t }: Pick<ImportPageDeps, "t"> & { fixedChatVersion: string | undefined; projectId: string }) {
  return (
    <section aria-label={t("chatTest")} className="project-tab-panel project-chat-tab">
      <ProjectChatTest fixedVersionId={fixedChatVersion} key={`${projectId}:${fixedChatVersion ?? "all"}`} />
    </section>
  );
}
