"use client";

import { type FormEvent, useMemo, useState } from "react";
import { Bot, CheckCircle2, Wrench, X } from "lucide-react";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { ChatWaitingIndicator } from "@/components/ChatWaitingIndicator";
import { FeedbackField } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { formatShortDateTime as formatDateTime } from "@/lib/dateFormat";
import { t as translate } from "@/lib/i18n";
import { useI18n } from "@/lib/i18nClient";
import type { AnswerEvaluation, ConversationEntry, Judgment, Translate } from "./documentChatModel";

/** Assistant answer with citations, judgment controls and the revision dialog (OPT424-038). */
export function AssistantMessage({ entry, canEvaluate, evaluation, extractionHref, onEvaluate }: { entry: ConversationEntry; canEvaluate: boolean; evaluation?: AnswerEvaluation; extractionHref: string; onEvaluate: (entry: ConversationEntry, value: Judgment, suggestion?: string) => Promise<void> }) {
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisionSuggestion, setRevisionSuggestion] = useState("");

  function openRevisionModal() {
    if (!canEvaluate) return;
    setRevisionSuggestion(evaluation?.suggestion ?? "");
    setRevisionOpen(true);
  }

  async function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const suggestion = revisionSuggestion.trim();
    if (!suggestion || !canEvaluate) return;
    await onEvaluate(entry, "needs_revision", suggestion);
    setRevisionOpen(false);
  }

  return (
    <article aria-busy={entry.loading || undefined} className="chat-message assistant-message">
      <div className="message-avatar"><Bot size={18} /></div>
      <div className="assistant-message-body">
        <small>{t("brandNomoSmartLiveBackend")} {entry.answeredAt ? `· ${formatDateTime(entry.answeredAt, locale)}` : ""}</small>
        {entry.loading ? <ChatWaitingIndicator label={t("documentChatQueryingStaging")} /> : entry.error ? <FeedbackField>{localize(entry.error)}</FeedbackField> : (
          <ChatResponseEvidence
            answer={entry.answer}
            answerFallback={t("documentChatNoVerifiableAnswer")}
            citations={entry.citations}
            citationsLabel={t("citations")}
            detailHref={extractionHref}
            idPrefix={`document-chat-${entry.id}`}
            noCitationsLabel={t("documentChatNoBackendCitation")}
          />
        )}
        <div className="answer-judgment" aria-label={t("documentChatAnswerJudgmentAria")}>
          <button className={evaluation?.judgment === "correct" ? "selected correct" : ""} disabled={!entry.recordId || !canEvaluate} onClick={() => { void onEvaluate(entry, "correct"); }} type="button"><CheckCircle2 size={16} /> {t("answerCorrect")}</button>
          <button className={evaluation?.judgment === "needs_revision" ? "selected needs-revision" : ""} disabled={!entry.recordId || !canEvaluate} onClick={openRevisionModal} type="button"><Wrench size={16} /> {t("answerNeedsRevision")}</button>
          {evaluation ? <span>{evaluation.judgment === "correct" ? t("documentChatRecordedCorrect") : format("documentChatRecordedSuggestion", { suggestion: evaluation.suggestion })}</span> : null}
        </div>
      </div>

      {revisionOpen ? (
        <Modal onEscape={() => setRevisionOpen(false)} aria-labelledby={`${entry.id}-revision-title`} className="modal-panel chat-small-modal">
            <div className="modal-header"><div><p className="eyebrow">{t("answerNeedsRevision")}</p><h2 id={`${entry.id}-revision-title`}>{t("revisionSuggestion")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={() => setRevisionOpen(false)} type="button"><X size={18} /></button></div>
            <form className="revision-suggestion-form" onSubmit={submitRevision}><label htmlFor={`${entry.id}-revision`}>{t("revisionSuggestion")}</label><textarea autoFocus id={`${entry.id}-revision`} onChange={(event) => setRevisionSuggestion(event.target.value)} placeholder={t("revisionPlaceholder")} required rows={5} value={revisionSuggestion} /><div className="modal-actions"><button className="action-button secondary" onClick={() => setRevisionOpen(false)} type="button">{t("cancel")}</button><button className="action-button" disabled={!revisionSuggestion.trim()} type="submit">{t("saveSuggestion")}</button></div></form>
          </Modal>
      ) : null}
    </article>
  );
}
