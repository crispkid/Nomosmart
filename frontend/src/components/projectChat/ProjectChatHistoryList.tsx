"use client";

import { Bot, MessageSquarePlus, Trash2 } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { ChatHistoryAuthor } from "@/components/ChatHistoryAuthor";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { chatConversationAccess } from "@/lib/chatConversationAccess";
import { useI18n } from "@/lib/i18nClient";
import type { ProjectConversation } from "./projectChatModel";

type ProjectChatHistoryListProps = {
  activateConversation: (conversation: ProjectConversation) => void;
  activeConversationId: string | null;
  currentUser: ReturnType<typeof useAuth>["currentUser"];
  historyBusy: boolean;
  historyCursor: string | null;
  historyError: string;
  historyStatus: "loading" | "ready" | "error";
  loadMoreHistory: () => Promise<void>;
  orderedConversations: ProjectConversation[];
  persistedConversationCount: number;
  setDeleteError: (value: string) => void;
  setDeleteTargetId: (value: string | null) => void;
};

/** Conversation history list with load-more and delete entry points (OPT424-038). */
export function ProjectChatHistoryList({ activateConversation, activeConversationId, currentUser, historyBusy, historyCursor, historyError, historyStatus, loadMoreHistory, orderedConversations, persistedConversationCount, setDeleteError, setDeleteTargetId }: ProjectChatHistoryListProps) {
  const { t, format, localize } = useI18n();
  return (
    <div className="project-conversation-history">
      <div className="project-history-title"><strong>{t("conversationHistory")}</strong><small>{format("projectChatConversationCount", { count: persistedConversationCount })}</small></div>
      <div className="project-history-list">
        {historyStatus === "loading" ? <div className="project-history-state"><Bot size={16} /><span>{t("projectChatHistoryLoading")}</span></div> : null}
        {historyStatus === "error" ? <FeedbackMessage tone="error"><Bot size={16} /><span><strong>{t("projectChatHistoryLoadFailed")}</strong><small>{localize(historyError)}</small></span></FeedbackMessage> : null}
        {historyStatus === "ready" && !orderedConversations.length ? <div className="project-history-state"><MessageSquarePlus size={16} /><span><strong>{t("projectChatHistoryEmptyTitle")}</strong><small>{t("projectChatHistoryEmptyHelp")}</small></span></div> : null}
        {historyStatus !== "loading" && orderedConversations.map((conversation) => {
          const title = conversation.history?.title || conversation.entries[0]?.question || t("newConversation");
          const draft = !conversation.persisted;
          const itemAccess = chatConversationAccess(conversation.history, currentUser?.user_id);
          return (
            <div className={`project-history-row${conversation.id === activeConversationId ? " active" : ""}${draft ? " draft" : ""}`} key={conversation.id}>
              <button aria-pressed={conversation.id === activeConversationId} className="project-history-select" onClick={() => activateConversation(conversation)} type="button">
                <MessageSquarePlus size={15} />
                <span><strong>{title.length > 22 ? `${title.slice(0, 22)}…` : title}{draft ? <em>{t("projectChatDraftBadge")}</em> : null}</strong><ChatHistoryAuthor name={draft ? currentUser?.display_name : conversation.history?.created_by_display_name} isMine={draft || itemAccess.isMine} readOnly={!draft && !itemAccess.canContinue} /><small>{draft ? format("projectChatDraftSummary", { documents: conversation.scopeIds.length, time: new Date(conversation.updatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) }) : format(conversation.entries.filter((entry) => entry.recordId && !entry.loading && !entry.error).length === 1 ? "projectChatHistorySummaryOne" : "projectChatHistorySummaryMany", { documents: conversation.scopeIds.length, count: conversation.entries.filter((entry) => entry.recordId && !entry.loading && !entry.error).length, time: new Date(conversation.updatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) })}</small></span>
              </button>
              {draft || itemAccess.canDelete ? <button aria-label={format("projectChatDeleteConversationAria", { title })} className="project-history-delete" onClick={() => { setDeleteTargetId(conversation.id); setDeleteError(""); }} type="button"><Trash2 size={14} /></button> : null}
            </div>
          );
        })}
        {historyCursor ? <button className="action-button secondary" disabled={historyBusy} onClick={() => void loadMoreHistory()} type="button">{t("chatHistoryLoadMore")}</button> : null}
      </div>
    </div>
  );
}
