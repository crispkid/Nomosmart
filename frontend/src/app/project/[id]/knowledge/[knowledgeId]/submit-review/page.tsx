"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, BarChart3, Check, CheckCircle2, ChevronDown, CircleUserRound, Clock3, Download, FileText, Image as ImageIcon, MessageSquareText, Network, Send, ShieldCheck, Table2, Tags, UsersRound } from "lucide-react";
import { AppShell, StatusBadge } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { getDocumentVersionSubmissionEvidence, getKnowledgeDetail, submitDocumentVersionReview, type ApprovalRequestResponse, type KnowledgeDetailResponse, type ProjectChatCitation, type ProjectChatRecordResponse, type SubmissionEvidenceResponse } from "@/lib/api";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

function evaluationLabel(value: ProjectChatRecordResponse["evaluation"], t: Translate) {
  if (value === "correct") return t("submitReviewEvaluationCorrect");
  if (value === "needs_revision") return t("submitReviewEvaluationNeedsRevision");
  return t("submitReviewEvaluationNotEvaluated");
}

function downloadTextFile(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function formatDateTime(value: string | null | undefined, locale: "en" | "zh") {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "en" ? "en-US" : "zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function citationSummary(record: ProjectChatRecordResponse) {
  return record.citations.map((citation) => `${citation.title ?? citation.document_id}|${citation.document_version_id}|${citation.chunk_id}${citation.page ? `|page ${citation.page}` : ""}`).join("; ");
}

export default function SubmitReviewPage() {
  const params = useParams<{ id: string; knowledgeId: string }>();
  const router = useRouter();
  const { apiFetch, authReady } = useAuth();
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [detail, setDetail] = useState<KnowledgeDetailResponse | null>(null);
  const [evidence, setEvidence] = useState<SubmissionEvidenceResponse | null>(null);
  const [chatRecords, setChatRecords] = useState<ProjectChatRecordResponse[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submissionResult, setSubmissionResult] = useState<ApprovalRequestResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [expandedConversationIds, setExpandedConversationIds] = useState<Set<string>>(() => new Set());
  const chatTestHref = `/project/${params.id}/knowledge/${params.knowledgeId}/chat-test`;
  const versionId = detail?.version.id;
  const canSubmitReview = Boolean(evidence?.can_submit_review && evidence.next_stage_allowed);

  useEffect(() => {
    if (!authReady) return;
    let cancelled = false;
    async function load() {
      try {
        const loaded = await getKnowledgeDetail(apiFetch, params.id, params.knowledgeId);
        if (cancelled) return;
        const submissionEvidence = await getDocumentVersionSubmissionEvidence(apiFetch, params.id, loaded.document.id, loaded.version.id);
        if (cancelled) return;
        setEvidence(submissionEvidence);
        setDetail(submissionEvidence.detail);
        setChatRecords(submissionEvidence.chat_records.map((record) => ({
          id: record.id,
          conversation_id: record.conversation_id,
          conversation_title: record.conversation_title,
          scope_mode: record.scope_mode as "document_staging" | "published" | null,
          selected_document_version_ids: record.selected_document_version_ids,
          question: record.question,
          answer: record.answer,
          citations: record.reference_docs as ProjectChatCitation[],
          evaluation: record.evaluation as ProjectChatRecordResponse["evaluation"],
          revision_suggestion: record.revision_suggestion,
          llm_model_id: null,
          prompt_version: null,
          token_usage: null,
          latency_ms: null,
          asked_at: record.asked_at,
          answered_at: record.answered_at
        })));
      } catch (error) {
        if (!cancelled) setLoadError(operationalErrorMessage(error, t, format, "submitReviewLoadFailed"));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [apiFetch, authReady, format, params.id, params.knowledgeId, t]);

  useEffect(() => {
    if (!submissionResult) return;
    const timer = window.setTimeout(() => {
      router.push("/approve");
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [router, submissionResult]);

  const conversations = useMemo(() => {
    const grouped = new Map<string, ProjectChatRecordResponse[]>();
    chatRecords.forEach((record) => {
      grouped.set(record.conversation_id, [...(grouped.get(record.conversation_id) ?? []), record]);
    });
    return Array.from(grouped.entries()).map(([id, records]) => ({
      id,
      title: records[0]?.conversation_title || records[0]?.question || t("submitReviewUntitledConversation"),
      updatedAt: records.map((record) => record.answered_at ?? record.asked_at).sort().at(-1) ?? "",
      turns: records
    }));
  }, [chatRecords, t]);

  const chunkCounts = useMemo(() => {
    const counts = { text: 0, image: 0, table: 0, chart: 0 };
    detail?.chunks.forEach((chunk) => {
      const type = String(chunk.content_type ?? "text").toLowerCase();
      if (type.includes("image")) counts.image += 1;
      else if (type.includes("table")) counts.table += 1;
      else if (type.includes("chart")) counts.chart += 1;
      else counts.text += 1;
    });
    return counts;
  }, [detail]);

  function downloadSubmissionChatRecords() {
    if (!chatRecords.length) return;
    const headers = ["conversation_id", "conversation_title", "question", "answer", "asked_at", "answered_at", "citations", "evaluation", "suggested_correction"];
    const escapeCsv = (value: string) => `"${value.replaceAll('"', '""')}"`;
    const rows = chatRecords.map((record) => [
      record.conversation_id,
      record.conversation_title ?? "",
      record.question,
      record.answer ?? "",
      record.asked_at,
      record.answered_at ?? "",
      citationSummary(record),
      record.evaluation,
      record.revision_suggestion ?? ""
    ].map(escapeCsv).join(","));
    downloadTextFile(`\uFEFF${headers.join(",")}\n${rows.join("\n")}`, `nomosmart-submission-chat-${new Date().toISOString().slice(0, 10)}.csv`);
  }

  function toggleConversation(conversationId: string) {
    setExpandedConversationIds((current) => {
      const next = new Set(current);
      if (next.has(conversationId)) next.delete(conversationId);
      else next.add(conversationId);
      return next;
    });
  }

  async function submitReview() {
    if (!detail) return;
    if (!canSubmitReview) {
      setSubmitError(t("submitReviewPermissionDenied"));
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      if (!evidence) return;
      const response = await submitDocumentVersionReview(apiFetch, params.id, detail.document.id, detail.version.id, {
        evidence_revision: evidence.evidence_revision,
        lock_version: evidence.lock_version
      });
      setSubmissionResult(response);
    } catch (error) {
      setSubmitError(operationalErrorMessage(error, t, format, "submitReviewFailed"));
    } finally {
      setSubmitting(false);
    }
  }

  const approvalSteps = [
    { label: t("submitReviewStepSubmitter"), person: t("submitReviewCurrentUser"), detail: t("submitReviewDocumentCreator"), icon: CircleUserRound, state: "current" },
    { label: t("submitReviewStepManager"), person: t("submitReviewManagerFromKeycloak"), detail: t("submitReviewFirstStage"), icon: ShieldCheck, state: "next" },
    { label: t("submitReviewStepOwner"), person: t("submitReviewAnyOwner"), detail: t("submitReviewSecondStage"), icon: UsersRound, state: "pending" },
    { label: t("publish"), person: t("submitReviewAuthorizedRole"), detail: t("submitReviewPublishDetail"), icon: CheckCircle2, state: "pending" }
  ] as const;
  const localizedBlockReasons = evidence?.block_reasons.map((reason) => operationalCodeMessage(reason, t, format, "submitReviewWaitingVersion")) ?? [];

  return (
    <AppShell title={t("submitForReview")}>
      <div className="project-context submission-page-context">
        <Link className="text-link" href={chatTestHref}><ArrowLeft size={16} /> {t("backToChatTest")}</Link>
        <StatusBadge status={detail?.version.status ?? "processing"} />
        <span>{detail?.pipeline?.status === "submission_ready" ? t("submitReviewStagingReady") : t("submitReviewLiveBackendSummary")}</span>
      </div>

      <section className="submission-shell" aria-labelledby="submission-summary-title">
        <header className="submission-heading">
          <div><p className="eyebrow">{t("submitReviewEyebrow")}</p><h2 id="submission-summary-title">{t("submissionSummary")}</h2><p>{t("submitReviewSummaryHelp")}</p></div>
            <div className="submission-readiness"><CheckCircle2 size={18} /><span><strong>{evidence?.next_stage_allowed ? t("submitReviewReady") : t("notificationLoading")}</strong><small>{localizedBlockReasons.length ? localizedBlockReasons.join(", ") : versionId ? t("submitReviewVersionIdReady") : t("submitReviewWaitingVersion")}</small></span></div>
        </header>
        {loadError ? <div className="batch-upload-error">{localize(loadError)}</div> : null}

        <div className="submission-summary-grid">
          <section className="submission-section submission-document-section">
            <div className="submission-section-title"><FileText size={18} /><h3>{t("documentSummary")}</h3></div>
            <div className="submission-document-identity"><span className="submission-file-icon"><FileText size={24} /></span><div><strong>{detail?.document.title ?? t("notificationLoading")}</strong><small>{detail?.document.source_type ?? ""}</small></div><StatusBadge status={detail?.document.status ?? "processing"} /></div>
            <dl className="submission-detail-list">
              <div><dt>{t("projectImportCurrentVersion")}</dt><dd><strong>{detail?.version.version_label ?? "-"}</strong> · {detail?.version.status ?? "-"}</dd></div>
              <div><dt>{t("submitReviewDocumentCode")}</dt><dd>{detail?.document.document_code ?? "-"}</dd></div>
              <div><dt>{t("projectImportSortUpdatedAt")}</dt><dd>{formatDateTime(detail?.document.updated_at, locale)}</dd></div>
              <div><dt>{t("labelStagingIndex")}</dt><dd className="submission-positive"><CheckCircle2 size={14} /> {detail?.pipeline?.status ?? t("pipelineNotStarted")}</dd></div>
            </dl>
          </section>

          <section className="submission-section submission-extraction-section">
            <div className="submission-section-title"><Tags size={18} /><h3>{t("extractionSummary")}</h3></div>
            <div className="submission-extraction-total"><strong>{detail?.chunks.length ?? 0}</strong><span>{t("submitReviewTotalChunks")}<small><CheckCircle2 size={13} /> {t("labelLiveChunks")}</small></span></div>
            <div className="submission-metrics">
              <span><FileText size={16} /><strong>{chunkCounts.text}</strong><small>{t("submitReviewText")}</small></span>
              <span><ImageIcon size={16} /><strong>{chunkCounts.image}</strong><small>{t("submitReviewImage")}</small></span>
              <span><Table2 size={16} /><strong>{chunkCounts.table}</strong><small>{t("submitReviewTable")}</small></span>
              <span><BarChart3 size={16} /><strong>{chunkCounts.chart}</strong><small>{t("labelChart")}</small></span>
            </div>
            <dl className="submission-model-list"><div><dt>{t("labelPipeline")}</dt><dd>{detail?.pipeline?.status ?? t("pipelineNotStarted")}</dd></div><div><dt>{t("pipelineCurrentStep")}</dt><dd>{detail?.pipeline?.current_step_name ?? "-"}</dd></div><div><dt>{t("submitReviewProgress")}</dt><dd>{detail?.pipeline?.progress_percent ?? 0}%</dd></div></dl>
          </section>

          <section className="submission-section submission-graph-section">
            <div className="submission-section-heading"><div className="submission-section-title"><Network size={18} /><h3>{t("graphSummary")}</h3></div><span className="submission-ready-label"><CheckCircle2 size={14} /> {t("labelLiveEvidence")}</span></div>
            <div className="graph-summary-row">
              <span><FileText size={17} /><small>{t("labelDocument")}</small><strong>1</strong><em>{t("submitReviewDocumentNode")}</em></span>
              <span><MessageSquareText size={17} /><small>{t("labelChunk")}</small><strong>{evidence?.graph.chunk_count ?? 0}</strong><em>{t("submitReviewChunkNode")}</em></span>
              <span><Tags size={17} /><small>{t("labelEvidence")}</small><strong>{evidence?.graph.node_count ?? 0}</strong><em>{t("submitReviewConversationRecord")}</em></span>
              <span><Network size={17} /><small>{t("labelCitations")}</small><strong>{evidence?.graph.edge_count ?? 0}</strong><em>{t("submitReviewTraceableCitation")}</em></span>
            </div>
            <div className="submission-graph-detail"><p><CheckCircle2 size={16} /><span><strong>{t("submitReviewSourceTraceability")}</strong><small>{t("submitReviewSourceTraceabilityHelp")}</small></span></p></div>
          </section>

          <section className="submission-section submission-chat-section">
            <div className="submission-section-heading">
              <div className="submission-section-title"><MessageSquareText size={18} /><h3>{t("chatTestSummary")}</h3><span className="submission-count-badge">{format("submitReviewConversationGroups", { count: conversations.length })}</span></div>
              <button className="action-button secondary" disabled={!chatRecords.length} onClick={downloadSubmissionChatRecords} type="button"><Download size={16} /> {t("downloadConversation")}</button>
            </div>
            {!conversations.length ? <div className="chat-empty-state"><MessageSquareText size={22} /><span>{t("submitReviewNoChatEvidence")}</span></div> : null}
            <div className="submission-conversation-list">
              {conversations.map((conversation) => {
                const expanded = expandedConversationIds.has(conversation.id);
                const evaluationCounts = conversation.turns.reduce((counts, turn) => ({ ...counts, [turn.evaluation]: counts[turn.evaluation] + 1 }), { correct: 0, needs_revision: 0, not_evaluated: 0 });
                return (
                  <article className={`submission-conversation-group${expanded ? " expanded" : ""}`} key={conversation.id}>
                    <button aria-controls={`${conversation.id}-turns`} aria-expanded={expanded} className="submission-conversation-toggle" onClick={() => toggleConversation(conversation.id)} type="button">
                      <span className="submission-conversation-main"><MessageSquareText size={17} /><span><strong>{conversation.title}</strong><small>{detail?.document.title ?? ""}</small></span></span>
                      <span className="submission-conversation-summary"><span>{format("submitReviewTurnCount", { count: conversation.turns.length })}</span><span>{t("submitReviewEvaluationCorrect")} {evaluationCounts.correct}</span><span>{t("submitReviewEvaluationNeedsRevision")} {evaluationCounts.needs_revision}</span><span>{t("submitReviewEvaluationNotEvaluated")} {evaluationCounts.not_evaluated}</span><span><Clock3 size={12} /> {formatDateTime(conversation.updatedAt, locale)}</span></span>
                      <ChevronDown className="submission-conversation-chevron" size={19} />
                    </button>
                    {expanded ? <div className="submission-chat-list" id={`${conversation.id}-turns`}>{conversation.turns.map((record, index) => <article key={record.id}><div className="submission-chat-question"><span>Q{index + 1}</span><strong>{record.question}</strong><span className={`review-evaluation ${record.evaluation}`}>{evaluationLabel(record.evaluation, t)}</span></div><ChatResponseEvidence answer={record.answer} answerContainerClassName="submission-chat-answer" answerFallback={t("submitReviewNoBackendAnswer")} answerLabel={t("submitReviewAnswer")} citations={record.citations} citationsContainerClassName="submission-chat-citations" citationsLabel={t("submitReviewCitations")} idPrefix={`submit-review-${record.id}`} noCitationsLabel={t("projectChatNoBackendCitation")} /><footer><span><Clock3 size={13} /> {t("submitReviewAsked")} {formatDateTime(record.asked_at, locale)} · {t("submitReviewAnswered")} {formatDateTime(record.answered_at, locale)}</span>{record.evaluation === "needs_revision" ? <p><strong>{t("submitReviewRevisionSuggestion")}：</strong>{record.revision_suggestion}</p> : <p>{record.evaluation === "not_evaluated" ? t("submitReviewPendingManualEvaluation") : t("submitReviewManualEvaluationCompleted")}</p>}</footer></article>)}</div> : null}
                  </article>
                );
              })}
            </div>
          </section>
        </div>

        <section className="submission-workflow">
          <div className="submission-section-title"><ShieldCheck size={18} /><h3>{t("approvalFlow")}</h3></div>
          <ol>{approvalSteps.map((step, index) => { const Icon = step.icon; return <li className={`workflow-step ${step.state}`} key={step.label}><span className="workflow-step-icon">{step.state === "current" ? <Check size={17} /> : <Icon size={17} />}</span><div><small>{step.label}</small><strong>{step.person}</strong><span>{step.detail}</span></div>{index < approvalSteps.length - 1 ? <i aria-hidden="true" /> : null}</li>; })}</ol>
        </section>

        <footer className="submission-actions">
          <p><ShieldCheck size={17} /><span>{t("submitReviewLockHelp")}</span></p>
          {!evidence?.can_submit_review ? <small className="field-error">{t("submitReviewPermissionDenied")}</small> : null}
          {evidence && !evidence.next_stage_allowed ? <small className="field-error">{localizedBlockReasons.join(", ")}</small> : null}
          {submitError ? <small className="field-error">{localize(submitError)}</small> : null}
          <button className="action-button" disabled={submitting || !detail || !canSubmitReview} onClick={() => { void submitReview(); }} type="button"><Send size={17} /> {submitting ? t("submitReviewSubmitting") : t("submitReview")}</button>
        </footer>
      </section>

      {submissionResult ? (
        <div className="modal-backdrop" role="presentation">
          <section aria-labelledby="submission-success-title" aria-modal="true" className="modal-panel submission-success-modal" role="dialog">
            <div className="modal-header">
              <div className="submission-success-title">
                <span><CheckCircle2 size={22} /></span>
                <div>
                  <p className="eyebrow">{t("submitReviewSubmissionCompleted")}</p>
                  <h2 id="submission-success-title">{t("submittedNextStage")}</h2>
                </div>
              </div>
            </div>
            <p>{t("submitReviewSuccessHelp")}</p>
            <dl className="submission-success-detail">
              <div>
                <dt>{t("submitReviewNextStageLabel")}</dt>
                <dd>{t("submitReviewNextStageManagerReview")}</dd>
              </div>
              <div>
                <dt>{t("submitReviewTaskIdLabel")}</dt>
                <dd>{submissionResult.current_task_id ?? "-"}</dd>
              </div>
              <div>
                <dt>{t("submitReviewDocumentVersionLabel")}</dt>
                <dd>{submissionResult.document_title ?? detail?.document.title ?? "-"}</dd>
                <small>{submissionResult.version_label ?? detail?.version.version_label ?? "-"}</small>
              </div>
              <div>
                <dt>{t("submitReviewRequestStatusLabel")}</dt>
                <dd>{submissionResult.status}</dd>
                <small>{formatDateTime(submissionResult.submitted_at, locale)}</small>
              </div>
            </dl>
            <p className="submission-redirect-note"><Clock3 size={15} /> {t("submitReviewRedirectingToWorkspace")}</p>
            <div className="modal-actions"><button className="action-button" onClick={() => router.push("/approve")} type="button">{t("submitReviewGoToApprovalCenter")}</button></div>
          </section>
        </div>
      ) : null}
    </AppShell>
  );
}
