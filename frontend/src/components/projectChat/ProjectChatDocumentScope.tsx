"use client";

import { Check, MessageSquarePlus, Search } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { useI18n } from "@/lib/i18nClient";
import type { ChatDocument } from "./projectChatModel";

type ProjectChatDocumentScopeProps = {
  allIds: string[];
  documentDisabledLabel: (document: ChatDocument) => string;
  documentSourceLabel: string;
  eligibleIds: string[];
  filtered: ChatDocument[];
  fixedVersionId?: string;
  isDocumentEligible: (document: ChatDocument) => boolean;
  query: string;
  scopeDirty: boolean;
  selectedIds: string[];
  setQuery: (value: string) => void;
  setSelectedIds: (value: string[]) => void;
  startScopedConversation: () => void;
  toggleDocument: (id: string) => void;
};

/** Reference document selection for the project chat sidebar (OPT424-038). */
export function ProjectChatDocumentScope({ allIds, documentDisabledLabel, documentSourceLabel, eligibleIds, filtered, fixedVersionId, isDocumentEligible, query, scopeDirty, selectedIds, setQuery, setSelectedIds, startScopedConversation, toggleDocument }: ProjectChatDocumentScopeProps) {
  const { t, format } = useI18n();
  return (
    <div className="project-document-region">
      <div className="project-chat-scope-head">
        <div><strong>{t("projectChatDocumentSelection")}</strong><small>{format("projectChatActiveDocumentCount", { source: documentSourceLabel, selected: selectedIds.length, total: eligibleIds.length })}</small></div>
        {fixedVersionId === undefined ? <div><button onClick={() => setSelectedIds(allIds)} type="button">{t("projectChatSelectAll")}</button><button onClick={() => setSelectedIds([])} type="button">{t("projectChatClearSelection")}</button></div> : null}
      </div>
      <label className="project-document-search"><Search size={15} /><input aria-label={t("projectChatSearchReferenceDocuments")} onChange={(event) => setQuery(event.target.value)} placeholder={t("projectChatSearchDocumentPlaceholder")} value={query} /></label>
      <div className="project-document-options">
        {filtered.map((document) => {
          const selected = selectedIds.includes(document.id);
          const eligible = isDocumentEligible(document);
          return <button aria-disabled={!eligible} aria-pressed={selected} className={`${selected ? "selected" : ""}${!eligible ? " disabled" : ""}`} disabled={!eligible} key={document.id} onClick={() => toggleDocument(document.id)} type="button"><span className="document-check">{selected ? <Check size={14} /> : null}</span><span><strong>{document.title}{!eligible ? <em>{documentDisabledLabel(document)}</em> : null}</strong><small>{document.version} · {document.source} · {format("projectChatChunkCountInline", { count: document.chunks })}{!eligible ? ` · ${t("projectChatDocumentUnavailableHelp")}` : ""}</small></span></button>;
        })}
      </div>
      {!selectedIds.length ? <FeedbackMessage tone="warning">{t("projectChatSelectAtLeastOne")}</FeedbackMessage> : null}
      {scopeDirty && selectedIds.length ? <button className="action-button scope-apply" onClick={startScopedConversation} type="button"><MessageSquarePlus size={16} /> {t("projectChatNewConversationWithScope")}</button> : null}
    </div>
  );
}
