"use client";

import { Bot, CheckCircle2, UserRound, Wrench } from "lucide-react";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { ChatWaitingIndicator } from "@/components/ChatWaitingIndicator";
import { FeedbackField } from "@/components/FeedbackMessage";
import { chatConversationAccess } from "@/lib/chatConversationAccess";
import { useI18n } from "@/lib/i18nClient";
import { retrievalLabel, type Entry, type Judgment } from "./projectChatModel";

type ProjectChatEntryPairProps = {
  access: ReturnType<typeof chatConversationAccess>;
  authorName: string;
  entry: Entry;
  judgments: Record<number, Judgment>;
  persistFeedback: (entry: Entry, evaluation: Judgment) => Promise<void>;
  setRevisionEntryId: (value: number | null) => void;
  setRevisionText: (value: string) => void;
};

/** One question and its answer, citations and judgment controls (OPT424-038). */
export function ProjectChatEntryPair({ access, authorName, entry, judgments, persistFeedback, setRevisionEntryId, setRevisionText }: ProjectChatEntryPairProps) {
  const { t, localize } = useI18n();
  return (
    <div className="chat-response-pair">
      <article className="chat-message user-message"><div className="message-avatar"><UserRound size={17} /></div><div className="user-message-body"><small>{authorName}</small><p>{entry.question}</p></div></article>
      <article aria-busy={entry.loading || undefined} className="chat-message assistant-message">
        <div className="message-avatar"><Bot size={17} /></div>
        <div className="assistant-message-body">
          <small>NomoSmart · {retrievalLabel(entry.retrievalStrategy)}</small>
          {entry.loading ? <ChatWaitingIndicator label={t("projectChatQueryingPublishedKnowledge")} /> : entry.error ? <FeedbackField>{localize(entry.error)}</FeedbackField> : (
            <ChatResponseEvidence
              answer={entry.answer}
              answerFallback={t("projectChatNoBackendAnswer")}
              citations={entry.citations ?? []}
              citationsLabel={t("citations")}
              idPrefix={`project-chat-${entry.id}`}
              noCitationsLabel={entry.status === "no_answer" ? t("projectChatNoVerifiableCitation") : t("projectChatNoBackendCitation")}
            />
          )}
          <div className="answer-judgment">
            <button disabled={!entry.recordId || !access.canEvaluate} className={judgments[entry.id] === "correct" ? "selected correct" : ""} onClick={() => void persistFeedback(entry, "correct")} type="button"><CheckCircle2 size={15} /> {t("answerCorrect")}</button>
            <button disabled={!entry.recordId || !access.canEvaluate} className={judgments[entry.id] === "revision" ? "selected needs-revision" : ""} onClick={() => { if (!access.canEvaluate) return; setRevisionEntryId(entry.id); setRevisionText(""); }} type="button"><Wrench size={15} /> {t("answerNeedsRevision")}</button>
          </div>
        </div>
      </article>
    </div>
  );
}
