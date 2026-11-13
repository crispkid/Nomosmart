"use client";

import type { RefObject } from "react";
import { Database, FilePlus2, Layers3, UploadCloud } from "lucide-react";
import { Panel } from "@/components/AppShell";
import type { ImportPageDeps } from "./pageDeps";

type KnowledgeSourceDropZoneProps = Pick<ImportPageDeps, "t"> & {
  active: boolean;
  dragDepthRef: RefObject<number>;
  onActiveChange: (active: boolean) => void;
  onOpenDataService: () => void;
  onOpenReference: () => void;
  onOpenUpload: (files?: File[]) => void;
};

/** Drop zone and source buttons for adding knowledge sources to a project (OPT424-038). */
export function KnowledgeSourceDropZone({ active, dragDepthRef, onActiveChange, onOpenDataService, onOpenReference, onOpenUpload, t }: KnowledgeSourceDropZoneProps) {
  return (
    <Panel title={t("projectImportAddKnowledgeSource")}>
      <div
        aria-label={t("projectImportDropAria")}
        className={`drop-zone project-source-drop-zone ${active ? "drag-active" : ""}`}
        onClick={() => onOpenUpload()}
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepthRef.current += 1;
          onActiveChange(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
          if (dragDepthRef.current === 0) onActiveChange(false);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          event.preventDefault();
          dragDepthRef.current = 0;
          onActiveChange(false);
          const files = Array.from(event.dataTransfer.files);
          if (files.length) onOpenUpload(files);
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpenUpload();
          }
        }}
        role="button"
        tabIndex={0}
      >
        <UploadCloud size={36} />
        <strong>{t("projectImportDropTitle")}</strong>
        <small>{t("projectImportDropHelp")}</small>
        <div className="drop-actions">
          <button className="action-button" onClick={(event) => { event.stopPropagation(); onOpenUpload(); }} type="button"><FilePlus2 size={17} /> {t("projectImportChooseFiles")}</button>
          <button className="action-button secondary" onClick={(event) => { event.stopPropagation(); onOpenDataService(); }} type="button"><Database size={17} /> {t("projectImportDataService")}</button>
          <button className="action-button secondary" title={t("projectImportReferenceOtherProject")} onClick={(event) => { event.stopPropagation(); onOpenReference(); }} type="button"><Layers3 size={17} /> {t("projectImportReferenceOtherProject")}</button>
        </div>
      </div>
    </Panel>
  );
}
