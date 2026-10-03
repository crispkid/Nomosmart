"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  CircleUserRound,
  Clock3,
  Download,
  FileCode2,
  FileText,
  Image as ImageIcon,
  Loader2,
  MessageSquareText,
  Network,
  RefreshCw,
  ShieldCheck,
  Table2,
  Tags,
  UsersRound,
  X,
  XCircle
} from "lucide-react";
import { AppShell, StatusBadge } from "@/components/AppShell";
import { ApprovalEvidenceViewer } from "@/components/ApprovalEvidenceViewer";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { DocumentGraphPreview } from "@/components/DocumentGraphPreview";
import { useAuth } from "@/components/AuthProvider";
import { approveApprovalTask, getApprovalTask, publishDocumentVersion, rejectApprovalTask, type ApiError, type ApprovalTaskDetail, type ProjectChatCitation } from "@/lib/api";
import { buildApprovalConversationCsv, canSubmitApprovalDecision } from "@/lib/approvalDetail";
import { reviewWorkflow, type ReviewStepState } from "@/lib/reviewPresentation";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { resolvedSourceMappings } from "@/lib/markdownSourceMapping";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";

type Evaluation = "correct" | "needs_revision" | "not_evaluated";
type Decision = "approve" | "reject";
type DecisionOutcome = { kind: "success" | "error"; title: string; detail: string; redirectToWorkspace?: boolean };
type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
type ApprovalConversation = {
  id: string;
  title: string;
  updatedAt: string;
  turns: {
    question: string;
    answer: string;
    time: string;
    citation: string;
    citations: ProjectChatCitation[];
    evaluation: Evaluation;
    suggestion: string;
  }[];
};

function evaluationLabel(value: Evaluation, t: Translate) {
  if (value === "correct") return t("submitReviewEvaluationCorrect");
  if (value === "needs_revision") return t("submitReviewEvaluationNeedsRevision");
  return t("submitReviewEvaluationNotEvaluated");
}

function stageLabel(stage: string, t: Translate) {
  return stage === "owner_review" ? t("approvalStageOwnerReview") : t("approvalStageManagerReview");
}

function priorityLabel(priority: string, t: Translate) {
  return priority === "High" ? t("approvalPriorityHigh") : t("approvalPriorityNormal");
}

function readOnlyReasonLabel(reason: string | null | undefined, t: Translate) {
  if (reason === "version_changed") return t("approvalEvidenceStaleReason");
  if (reason === "task_completed") return t("approvalTaskCompletedReason");
  if (reason === "approval_actor_required") return t("approvalActorRequired");
  return t("approvalReadOnlyReason");
}

function approvalDecisionSuccessOutcome(decision: Decision, stage: string, t: Translate): DecisionOutcome {
  if (decision === "reject") {
    return { kind: "success", title: t("approvalRejectSubmitted"), detail: t("approvalRejectNextStep"), redirectToWorkspace: true };
  }
  if (stage === "owner_review") {
    return { kind: "success", title: t("approvalOwnerApproveSubmitted"), detail: t("approvalOwnerApproveNextStep"), redirectToWorkspace: true };
  }
  return { kind: "success", title: t("approvalManagerApproveSubmitted"), detail: t("approvalManagerApproveNextStep"), redirectToWorkspace: true };
}

function sourceLabelFromMapping(sourceMapping: unknown[], fallback: string, format: Format) {
  const first = sourceMapping.find((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  if (!first) return fallback;
  const page = typeof first.page === "number" || typeof first.page === "string" ? first.page : 1;
  const section = typeof first.section === "number" || typeof first.section === "string" ? first.section : 1;
  const kind = typeof first.type === "string" ? first.type : typeof first.kind === "string" ? first.kind : "paragraph";
  if (kind === "image") return format("approvalEvidenceSourceLabelImage", { page });
  if (kind === "table") return format("approvalEvidenceSourceLabelTable", { page });
  if (kind === "chart") return format("approvalEvidenceSourceLabelChart", { page });
  return format("approvalEvidenceSourceLabelParagraph", { page, section });
}

function sourceAnchorFromMapping(sourceMapping: unknown[], fallback: string) {
  const first = sourceMapping.find((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
  const mappedAnchor = first?.sourceAnchor ?? first?.source_anchor ?? first?.anchor;
  return typeof mappedAnchor === "string" && mappedAnchor ? mappedAnchor : fallback;
}

function downloadTextFile(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function ApprovalDetailPage() {
  const params = useParams<{ approvalTaskId: string }>();
  const router = useRouter();
  const { apiFetch } = useAuth();
  const { locale, format, localize } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const [liveDetail, setLiveDetail] = useState<ApprovalTaskDetail | null>(null);
  const [liveLoading, setLiveLoading] = useState(true);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveErrorStatus, setLiveErrorStatus] = useState<number | null>(null);
  const [loadedTaskId, setLoadedTaskId] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const loadPending = liveLoading || loadedTaskId !== params.approvalTaskId;
  const [expandedConversationIds, setExpandedConversationIds] = useState<Set<string>>(() => new Set());
  const [graphOpen, setGraphOpen] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [decisionOutcome, setDecisionOutcome] = useState<DecisionOutcome | null>(null);
  const [submittingDecision, setSubmittingDecision] = useState(false);
  const [publishingVersion, setPublishingVersion] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getApprovalTask(apiFetch, params.approvalTaskId).then((detail) => {
      if (!cancelled) {
        setLiveDetail(detail);
        setLiveError(null);
        setLiveErrorStatus(null);
      }
    }).catch((error: Error) => {
      if (!cancelled) {
        setLiveDetail(null);
        setLiveError(operationalErrorMessage(error, t, format, "approvalLoadFailed"));
        setLiveErrorStatus((error as Partial<ApiError>).status ?? null);
      }
    }).finally(() => {
      if (!cancelled) {
        setLoadedTaskId(params.approvalTaskId);
        setLiveLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [apiFetch, format, loadAttempt, params.approvalTaskId, t]);

  useEffect(() => {
    if (!decisionOutcome?.redirectToWorkspace) return;
    const timer = window.setTimeout(() => {
      router.push("/approve");
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [decisionOutcome, router]);

  const evidenceManifest = liveDetail?.evidence_manifest as {
    graph?: { node_count?: number; edge_count?: number; chunk_count?: number; status?: string };
    models?: Record<string, { name?: string; type?: string; provider?: string }>;
    validation?: { runs?: Array<{ id: string; status: string; total: number; completed: number; failed: number }> };
    actors?: {
      manager?: { given_name?: string | null; family_name?: string | null; display_name?: string; email?: string } | null;
      owners?: Array<{ given_name?: string | null; family_name?: string | null; display_name?: string; email?: string }>;
    };
  } | null;
  const manifestModels = Object.values(evidenceManifest?.models ?? {});
  const approval = liveDetail?.task.id === params.approvalTaskId ? {
    id: liveDetail.task.id,
    project: liveDetail.task.project_name ?? `Project ${liveDetail.task.project_id.slice(0, 8)}`,
    document: liveDetail.document.title,
    version: liveDetail.version.version_label,
    editor: formatPersonName({ given_name: liveDetail.request.submitter_given_name, family_name: liveDetail.request.submitter_family_name, display_name: liveDetail.request.submitter_name }, locale) || liveDetail.request.submitter_email || liveDetail.request.submitter_id.slice(0, 8),
    manager: evidenceManifest?.actors?.manager ? formatPersonName(evidenceManifest.actors.manager, locale) || evidenceManifest.actors.manager.email || liveDetail.task.assignee_user_id?.slice(0, 8) || t("approvalOwnerGroup") : liveDetail.task.assignee_user_id?.slice(0, 8) ?? t("approvalOwnerGroup"),
    owners: evidenceManifest?.actors?.owners?.map((owner) => formatPersonName(owner, locale) || owner.email || t("approvalProjectOwners")) ?? [t("approvalProjectOwners")],
    stage: liveDetail.task.review_stage,
    submittedAt: new Date(liveDetail.task.submitted_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW"),
    status: liveDetail.task.status,
    priority: liveDetail.request.priority,
    sourceType: liveDetail.document.source_type
  } : null;

  const displayChunks = useMemo(() => {
    if (!liveDetail?.chunks.length) return [];
    return liveDetail.chunks.map((chunk) => ({
      id: chunk.id,
      index: chunk.chunk_index,
      type: (["text", "image", "table", "chart"].includes(chunk.content_type) ? chunk.content_type : "text") as "text" | "image" | "table" | "chart",
      title: chunk.title || format("knowledgeDetailChunkTitle", { number: chunk.chunk_index }),
      page: chunk.chunk_index,
      sourceAnchor: sourceAnchorFromMapping(chunk.source_mapping, `chunk-${chunk.chunk_index}`),
      sourceMappings: resolvedSourceMappings(chunk.source_mapping),
      sourceLabel: sourceLabelFromMapping(chunk.source_mapping, format("knowledgeDetailChunkLabel", { number: chunk.chunk_index }), format),
      tokens: chunk.token_count ?? 0,
      confidence: chunk.confidence_score ?? 0,
      tags: chunk.tags,
      tagDetails: chunk.tag_details,
      content: chunk.content,
      displayMarkdown: chunk.display_markdown,
      markdownContent: chunk.markdown_content
    }));
  }, [format, liveDetail]);
  const displayConversations = useMemo<ApprovalConversation[]>(() => {
    if (!liveDetail?.chat_records.length) return [];
    const grouped = new Map<string, ApprovalConversation>();
    for (const record of liveDetail.chat_records) {
      const group = grouped.get(record.conversation_id) ?? {
        id: record.conversation_id,
        title: record.question.length > 24 ? `${record.question.slice(0, 24)}...` : record.question,
        updatedAt: new Date(record.answered_at || record.asked_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW"),
        turns: []
      };
      group.turns.push({
        question: record.question,
        answer: record.answer || t("approvalNoAnswerGenerated"),
        time: new Date(record.answered_at || record.asked_at).toLocaleTimeString(locale === "en" ? "en-US" : "zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        citation: record.reference_docs.length ? `${record.reference_docs.length} live references` : `${approval?.document ?? "Document"} · ${approval?.version ?? ""}`,
        citations: record.reference_docs,
        evaluation: (["correct", "needs_revision", "not_evaluated"].includes(record.evaluation) ? record.evaluation : "not_evaluated") as Evaluation,
        suggestion: ""
      });
      grouped.set(record.conversation_id, group);
    }
    return [...grouped.values()];
  }, [approval?.document, approval?.version, liveDetail, locale, t]);
  const tags = useMemo(() => Array.from(new Set(displayChunks.flatMap((chunk) => chunk.tags))), [displayChunks]);

  if (!approval && !loadPending) {
    const notFound = liveErrorStatus === 404;
    return (
      <AppShell title={t("approvalDetail")}>
        <section className="approval-not-found" role="alert">
          <XCircle size={34} />
          <h2>{notFound ? t("approvalTaskNotFound") : liveErrorStatus === 403 ? t("apiForbidden") : t("approvalLoadFailed")}</h2>
          <p>{notFound ? t("approvalTaskNotFoundHelp") : liveError ?? t("approvalLoadFailed")}</p>
          <div className="approval-error-actions">
          {!notFound ? <button className="action-button secondary" type="button" onClick={() => {
            setLiveLoading(true);
            setLiveDetail(null);
            setLiveError(null);
            setLiveErrorStatus(null);
            setLoadAttempt((attempt) => attempt + 1);
          }}><RefreshCw size={16} /> {t("retry")}</button> : null}
          <Link className="action-button secondary" href="/approve"><ArrowLeft size={16} /> {t("backToApprovalWorkspace")}</Link>
          </div>
        </section>
      </AppShell>
    );
  }

  if (!approval) {
    return <AppShell title={t("approvalDetail")}><section className="empty-state" role="status" aria-busy="true"><Loader2 size={20} className="loading-spinner" aria-hidden="true" /> {t("approvalLoadingTask")}</section></AppShell>;
  }

  const isOwnerReview = approval.stage === "owner_review";
  const graphChunks = displayChunks.map((chunk) => ({
    ...chunk,
    chunkIndex: chunk.index,
    tagDetails: (chunk.tagDetails ?? []).map((tag) => ({ id: tag.tag_id, text: tag.tag_text, source: tag.source }))
  }));
  const currentStageLabel = stageLabel(approval.stage, t);
  const reviewRecords = liveDetail?.review_records ?? [];
  const readOnly = liveDetail?.read_only ?? true;
  const readOnlyReason = readOnlyReasonLabel(liveDetail?.read_only_reason, t);
  const canDecide = !submittingDecision && !publishingVersion && decisionOutcome?.kind !== "success" && !readOnly && liveDetail?.task.status === "pending";
  const canPublish = !submittingDecision && !publishingVersion && liveDetail?.version.status === "approved" && liveDetail.document.capabilities?.can_publish === true;
  const contentCounts = displayChunks.reduce((counts, chunk) => ({ ...counts, [chunk.type]: counts[chunk.type] + 1 }), { text: 0, image: 0, table: 0, chart: 0 });
  const averageConfidence = displayChunks.length ? Math.round(displayChunks.reduce((sum, chunk) => sum + chunk.confidence, 0) / displayChunks.length * 100) : 0;
  const workflow = liveDetail ? reviewWorkflow(liveDetail) : { manager: "pending", owner: "pending", publish: "pending" } as const;
  const workflowDetail = (state: ReviewStepState) => state === "complete" ? t("approvalWorkflowApproved")
    : state === "rejected" ? t("statusReviewRejected") : state === "cancelled" ? t("approvalWorkflowCancelled")
    : state === "current" ? t("approvalWorkflowPendingReview") : t("approvalWorkflowNotStarted");
  const workflowSteps = [
    { label: t("submitReviewStepSubmitter"), person: approval.editor, detail: t("approvalWorkflowSubmitted"), icon: CircleUserRound, state: "complete" },
    { label: t("submitReviewStepManager"), person: approval.manager, detail: workflowDetail(workflow.manager), icon: ShieldCheck, state: workflow.manager },
    { label: t("submitReviewStepOwner"), person: t("submitReviewAnyOwner"), detail: workflowDetail(workflow.owner), icon: UsersRound, state: workflow.owner },
    { label: t("publish"), person: t("submitReviewAuthorizedRole"), detail: workflow.publish === "complete" ? t("statusPublishedActive") : workflow.publish === "current" ? t("statusPublishing") : t("approvalWorkflowPublishAfterApproval"), icon: CheckCircle2, state: workflow.publish }
  ];

  function toggleConversation(id: string) {
    setExpandedConversationIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function downloadConversationRecords() {
    downloadTextFile(buildApprovalConversationCsv(displayConversations), `nomosmart-approval-${params.approvalTaskId}-${approval?.version ?? "unknown"}.csv`);
  }

  function closeDecision() {
    setDecision(null);
    setComment("");
  }

  async function submitDecision() {
    if (!decision || !canSubmitApprovalDecision(decision, comment)) return;
    setSubmittingDecision(true);
    setDecisionOutcome(null);
    try {
      if (liveDetail) {
        const submittedDecision = decision;
        const submittedStage = liveDetail.task.review_stage;
        if (submittedDecision === "approve") await approveApprovalTask(apiFetch, liveDetail.task.id, { lock_version: liveDetail.task.lock_version, comment });
        else await rejectApprovalTask(apiFetch, liveDetail.task.id, { lock_version: liveDetail.task.lock_version, comment });
        const refreshed = await getApprovalTask(apiFetch, liveDetail.task.id).catch(() => null);
        if (refreshed) setLiveDetail(refreshed);
        setDecisionOutcome(approvalDecisionSuccessOutcome(submittedDecision, submittedStage, t));
      }
      closeDecision();
    } catch (error) {
      setDecisionOutcome({ kind: "error", title: t("approvalDecisionFailed"), detail: operationalErrorMessage(error, t, format, "approvalDecisionFailed") });
    } finally {
      setSubmittingDecision(false);
    }
  }

  async function publishLiveVersion() {
    if (!liveDetail) return;
    setPublishingVersion(true);
    setPublishError(null);
    setResult(null);
    try {
      const result = await publishDocumentVersion(apiFetch, liveDetail.version.id, { lock_version: liveDetail.version.lock_version, impact_confirmed: true });
      setResult(format("approvalPublishedGeneration", { generation: result.publication_generation }));
    } catch (error) {
      setPublishError(operationalErrorMessage(error, t, format, "approvalPublishFailed"));
    } finally {
      setPublishingVersion(false);
    }
  }

  return (
    <AppShell title={t("approvalDetail")}>
      <div className="project-context submission-page-context">
        <Link className="text-link" href="/approve"><ArrowLeft size={16} /> {t("backToApprovalWorkspace")}</Link>
        <StatusBadge status={approval.status} />
        <span>{currentStageLabel}</span>
        <span className="approval-priority">{priorityLabel(approval.priority, t)}</span>
      </div>

      <section className="submission-shell approval-detail-shell" aria-labelledby="approval-summary-title">
        <div className="live-data-badge"><CheckCircle2 size={14} /> {t("approvalLivePublishPath")}</div>
        {readOnly ? (
          <div className="approval-readonly-alert" role="status">
            <ShieldCheck size={17} />
            <span><strong>{t("approvalReadOnlyEvidence")}</strong><small>{readOnlyReason}</small></span>
          </div>
        ) : null}
        <header className="submission-heading">
          <div>
            <p className="eyebrow">{t("approvalEvidenceReviewEyebrow")}</p>
            <h2 id="approval-summary-title">{t("approvalEvidenceSummary")}</h2>
            <p>{t("approvalEvidenceHelper")}</p>
          </div>
          <div className="submission-readiness"><ShieldCheck size={18} /><span><strong>{currentStageLabel}</strong><small>{t("approvalStagingEvidenceLocked")}</small></span></div>
        </header>

        <section className="approval-context-strip" aria-label={t("approvalSubmissionInfo")}>
          <div><small>{t("approvalProjectLabel")}</small><strong>{approval.project}</strong></div>
          <div><small>{t("approvalSubmitterManagerLabel")}</small><strong>{approval.editor} / {approval.manager}</strong></div>
          <div><small>{t("approvalProjectOwners")}</small><strong>{approval.owners.join(" / ")}</strong></div>
          <div><small>{t("approvalSubmissionReason")}</small><strong>{t("approvalSubmissionReasonContent")}</strong></div>
        </section>

        <div className="submission-summary-grid">
          <section className="submission-section submission-document-section">
            <div className="submission-section-title"><FileText size={18} /><h3>{t("documentSummary")}</h3></div>
            <div className="submission-document-identity">
              <span className="submission-file-icon"><FileText size={24} /></span>
              <div><strong>{approval.document}</strong><small>{approval.sourceType} · {liveDetail?.version.canonical_extension || liveDetail?.version.mime_type || t("approvalArtifactUnknown")} · {liveDetail?.version.file_size ? format("approvalFileSizeBytes", { count: liveDetail.version.file_size }) : t("approvalFileSizeUnknown")}</small></div>
              <StatusBadge status={approval.status} />
            </div>
            <dl className="submission-detail-list">
              <div><dt>{t("projectImportCurrentVersion")}</dt><dd>{approval.version}</dd></div>
              <div><dt>{t("approvalDocumentStatus")}</dt><dd>{approval.status}</dd></div>
              <div><dt>{t("approvalCreator")}</dt><dd>{approval.editor}</dd></div>
              <div><dt>{t("approvalSubmittedAt")}</dt><dd>{approval.submittedAt}</dd></div>
              <div><dt>{t("pipelineStatus")}</dt><dd className="submission-positive"><CheckCircle2 size={14} /> {t("pipelineWaiting")} {currentStageLabel}</dd></div>
              <div><dt>{t("approvalEvidenceFreshness")}</dt><dd className={liveDetail?.evidence_stale ? "field-error" : "submission-positive"}>{liveDetail?.evidence_stale ? t("approvalEvidenceStale") : t("approvalEvidenceCurrent")}</dd></div>
            </dl>
          </section>

          <section className="submission-section submission-extraction-section">
            <div className="submission-section-title"><Tags size={18} /><h3>{t("extractionSummary")}</h3></div>
            <div className="submission-extraction-total"><strong>{displayChunks.length}</strong><span>{t("submitReviewTotalChunks")}<small><CheckCircle2 size={13} /> {t("approvalExtractionCompleted")}</small></span></div>
            <div className="submission-metrics">
              <span><FileText size={16} /><strong>{contentCounts.text}</strong><small>{t("submitReviewText")}</small></span>
              <span><ImageIcon size={16} /><strong>{contentCounts.image}</strong><small>{t("submitReviewImage")}</small></span>
              <span><Table2 size={16} /><strong>{contentCounts.table}</strong><small>{t("submitReviewTable")}</small></span>
              <span><BarChart3 size={16} /><strong>{contentCounts.chart}</strong><small>{t("chunkChart")}</small></span>
            </div>
            <dl className="submission-model-list"><div><dt>LLM</dt><dd>{manifestModels.find((model) => model.type === "Chat")?.name ?? t("approvalByVersionMetadata")}</dd></div><div><dt>Embedding</dt><dd>{manifestModels.find((model) => model.type === "Embedding")?.name ?? t("approvalByVersionMetadata")}</dd></div><div><dt>{t("approvalAverageConfidence")}</dt><dd>{averageConfidence}%</dd></div></dl>
          </section>

          <section className="submission-section submission-graph-section">
            <div className="submission-section-heading">
              <div className="submission-section-title"><Network size={18} /><h3>{t("graphSummary")}</h3></div>
              <button className="action-button secondary" onClick={() => setGraphOpen(true)} type="button"><Network size={16} /> {t("viewGraphPreview")}</button>
            </div>
            <div className="graph-summary-row">
              <span><FileText size={17} /><small>{t("approvalGraphDocument")}</small><strong>1</strong><em>{t("submitReviewDocumentNode")}</em></span>
              <span><MessageSquareText size={17} /><small>{t("approvalGraphChunk")}</small><strong>{evidenceManifest?.graph?.chunk_count ?? 0}</strong><em>{t("submitReviewChunkNode")}</em></span>
              <span><Tags size={17} /><small>{t("approvalGraphTag")}</small><strong>{tags.length}</strong><em>{t("approvalTagNode")}</em></span>
              <span><Network size={17} /><small>{t("approvalGraphEdges")}</small><strong>{evidenceManifest?.graph?.edge_count ?? 0}</strong><em>{t("approvalTraceableRelation")}</em></span>
            </div>
            <div className="submission-graph-detail">
              <div><strong>{t("approvalContentTypeCoverage")}</strong><span><FileText size={15} /> {t("submitReviewText")}</span><span><ImageIcon size={15} /> {t("submitReviewImage")}</span><span><Table2 size={15} /> {t("submitReviewTable")}</span><span><BarChart3 size={15} /> {t("chunkChart")}</span></div>
              <p><CheckCircle2 size={16} /><span><strong>{t("approvalSourceTraceabilityComplete")}</strong><small>{t("approvalStagingGraphHelp")}</small></span></p>
            </div>
          </section>

          <section className="submission-section submission-chat-section">
            <div className="submission-section-heading">
              <div className="submission-section-title"><MessageSquareText size={18} /><h3>{t("chatTestSummary")}</h3><span className="submission-count-badge">{format("submitReviewConversationGroups", { count: displayConversations.length })}</span></div>
              <button className="action-button secondary" onClick={downloadConversationRecords} type="button"><Download size={16} /> {t("downloadConversation")}</button>
            </div>
            <div className="submission-conversation-list">
              {displayConversations.map((conversation) => {
                const expanded = expandedConversationIds.has(conversation.id);
                const counts = conversation.turns.reduce((total, turn) => ({ ...total, [turn.evaluation]: total[turn.evaluation] + 1 }), { correct: 0, needs_revision: 0, not_evaluated: 0 });
                return (
                  <article className={`submission-conversation-group${expanded ? " expanded" : ""}`} key={conversation.id}>
                    <button aria-controls={`${conversation.id}-turns`} aria-expanded={expanded} className="submission-conversation-toggle" onClick={() => toggleConversation(conversation.id)} type="button">
                      <span className="submission-conversation-main"><MessageSquareText size={17} /><span><strong>{conversation.title}</strong><small>{approval.document} · {approval.version}</small></span></span>
                      <span className="submission-conversation-summary"><span>{format("submitReviewTurnCount", { count: conversation.turns.length })}</span><span>{t("submitReviewEvaluationCorrect")} {counts.correct}</span><span>{t("submitReviewEvaluationNeedsRevision")} {counts.needs_revision}</span><span>{t("submitReviewEvaluationNotEvaluated")} {counts.not_evaluated}</span><span><Clock3 size={12} /> {conversation.updatedAt}</span></span>
                      <ChevronDown className="submission-conversation-chevron" size={19} />
                    </button>
                    {expanded ? <div className="submission-chat-list" id={`${conversation.id}-turns`}>{conversation.turns.map((turn, index) => (
                      <article key={`${conversation.id}-${turn.time}`}>
                        <div className="submission-chat-question"><span>Q{index + 1}</span><strong>{turn.question}</strong><span className={`review-evaluation ${turn.evaluation}`}>{evaluationLabel(turn.evaluation, t)}</span></div>
                        <ChatResponseEvidence answer={turn.answer} answerContainerClassName="submission-chat-answer" answerFallback={t("approvalNoAnswerGenerated")} answerLabel={t("submitReviewAnswer")} citations={turn.citations} citationsContainerClassName="submission-chat-citations" citationsLabel={t("submitReviewCitations")} idPrefix={`approval-${conversation.id}-${index + 1}`} noCitationsLabel={t("projectChatNoBackendCitation")} />
                        <footer><span><Clock3 size={13} /> {t("approvalQuestionAnswerTime")} {turn.time}</span><p>{turn.suggestion ? <><strong>{t("submitReviewRevisionSuggestion")}：</strong>{turn.suggestion}</> : turn.evaluation === "not_evaluated" ? t("submitReviewPendingManualEvaluation") : t("submitReviewManualEvaluationCompleted")}</p></footer>
                      </article>
                    ))}</div> : null}
                  </article>
                );
              })}
            </div>
          </section>
        </div>

        <section className="approval-evidence-section">
          <div className="submission-section-title"><FileCode2 size={18} /><h3>{t("sourceEvidence")}</h3></div>
          <ApprovalEvidenceViewer
            chunks={displayChunks}
            documentLayout={liveDetail?.document_layout ?? null}
            documentTags={liveDetail?.document_tags ?? []}
            documentTitle={approval.document}
            markdownArtifactReasonCode={liveDetail?.markdown_artifact_reason_code ?? null}
            markdownText={liveDetail?.markdown_text ?? null}
            originalFile={liveDetail?.original_file ?? null}
            sourceText={liveDetail?.source_text ?? null}
            version={approval.version}
          />
        </section>

        <section className="approval-secondary-grid">
          <article>
            <div className="submission-section-title"><Table2 size={18} /><h3>{t("batchValidation")}</h3></div>
            {(evidenceManifest?.validation?.runs ?? []).length ? (evidenceManifest?.validation?.runs ?? []).map((run) => <div className="approval-validation-result" key={run.id}><CheckCircle2 size={22} /><div><strong>{run.status}</strong><p>{run.completed} / {run.total} · {t("statusFailed")} {run.failed}</p><small>{run.id}</small></div></div>) : <div className="approval-validation-result"><Clock3 size={22} /><div><strong>{t("approvalNoLiveValidationEvidence")}</strong><p>{t("approvalNoLiveValidationEvidenceHelp")}</p><small>{t("approvalScope")}：{approval.document} · {approval.version}</small></div></div>}
          </article>
          <article>
            <div className="submission-section-title"><Clock3 size={18} /><h3>{t("reviewHistory")}</h3></div>
            <ol className="approval-history">
              {reviewRecords.length ? reviewRecords.map((record) => <li key={record.id}><span><CheckCircle2 size={15} /></span><div><strong>{record.review_stage} · {record.status}</strong><p>{record.reviewer_id.slice(0, 8)} · {new Date(record.created_at).toLocaleString(locale === "en" ? "en-US" : "zh-TW")} · {record.comment || t("approvalNoComment")}</p></div></li>) : <li><span><Clock3 size={15} /></span><div><strong>{t("approvalNoLiveReviewHistory")}</strong><p>{t("approvalNoLiveReviewHistoryHelp")}</p></div></li>}
              {liveDetail?.task.status === "pending" ? <li className="current"><span><Clock3 size={15} /></span><div><strong>{t("pipelineWaiting")}{currentStageLabel}</strong><p>{isOwnerReview ? approval.owners.join(" / ") : approval.manager}</p></div></li> : null}
            </ol>
          </article>
        </section>

        <section className="submission-workflow">
          <div className="submission-section-title"><ShieldCheck size={18} /><h3>{t("approvalFlow")}</h3></div>
          <ol>{workflowSteps.map((step, index) => { const Icon = step.icon; return <li className={`workflow-step ${step.state}`} key={step.label}><span className="workflow-step-icon">{step.state === "complete" ? <CheckCircle2 size={17} /> : <Icon size={17} />}</span><div><small>{step.label}</small><strong>{step.person}</strong><span>{step.detail}</span></div>{index < workflowSteps.length - 1 ? <i aria-hidden="true" /> : null}</li>; })}</ol>
        </section>

        <footer aria-busy={publishingVersion} className="submission-actions approval-decision-bar">
          <p><ShieldCheck size={17} /><span>{t("approvalOptimisticLockHelp")}</span></p>
          {decisionOutcome ? (
            <div className={`approval-result ${decisionOutcome.kind === "error" ? "reject" : "approve"}`}>
              {decisionOutcome.kind === "error" ? <XCircle size={17} /> : <CheckCircle2 size={17} />}
              <span><strong>{localize(decisionOutcome.title)}</strong><small>{localize(decisionOutcome.detail)}</small></span>
            </div>
          ) : result ? (
            <div className="approval-result approve"><CheckCircle2 size={17} /> {localize(result)}</div>
          ) : (
            <div className="approval-decision-stack">
              {publishError ? (
                <div className="approval-result reject" role="alert">
                  <XCircle size={17} />
                  <span><strong>{t("approvalPublishFailed")}</strong><small>{localize(publishError)}</small></span>
                </div>
              ) : null}
              <div aria-live="polite" className="approval-decision-actions" role={publishingVersion ? "status" : undefined}>
                <button className="action-button" disabled={!canDecide} onClick={() => { setDecisionOutcome(null); setDecision("approve"); }} type="button"><ShieldCheck size={17} /> {t("approve")}</button>
                <button className="action-button danger" disabled={!canDecide} onClick={() => { setDecisionOutcome(null); setDecision("reject"); }} type="button"><XCircle size={17} /> {t("reject")}</button>
                {liveDetail?.version.status === "approved" ? (
                  <button className="action-button secondary" disabled={!canPublish} onClick={() => { void publishLiveVersion(); }} type="button">
                    {publishingVersion ? <Loader2 className="spin" size={17} /> : <CheckCircle2 size={17} />}
                    {publishingVersion ? t("approvalPublishing") : t("publish")}
                  </button>
                ) : null}
              </div>
            </div>
          )}
        </footer>
      </section>

      {graphOpen ? <div className="modal-backdrop" role="presentation"><section aria-labelledby="approval-graph-title" aria-modal="true" className="modal-panel document-graph-modal" role="dialog"><div className="modal-header"><div><p className="eyebrow">{format("approvalStagingGraphVersion", { version: approval.version })}</p><h2 id="approval-graph-title">{t("approvalPreReviewGraphPreview")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={() => setGraphOpen(false)} type="button"><X size={18} /></button></div><DocumentGraphPreview documentTitle={approval.document} graphChunks={graphChunks} version={approval.version} /></section></div> : null}

      {decision ? <div className="modal-backdrop" role="presentation"><section aria-labelledby="approval-decision-title" aria-modal="true" className="modal-panel approval-decision-modal" role="dialog"><div className="modal-header"><div><p className="eyebrow">{currentStageLabel}</p><h2 id="approval-decision-title">{decision === "approve" ? t("approvalApproveDocumentVersion") : t("approvalRejectDocumentVersion")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={closeDecision} type="button"><X size={18} /></button></div><p>{approval.document} · {approval.version}</p><label><span>{decision === "approve" ? t("approvalCommentOptional") : t("rejectionReasonRequired")}</span><textarea aria-invalid={!canSubmitApprovalDecision(decision, comment)} autoFocus onChange={(event) => setComment(event.target.value)} placeholder={decision === "approve" ? t("approvalApproveCommentPlaceholder") : t("approvalRejectReasonPlaceholder")} rows={4} value={comment} /></label>{decision === "reject" && !canSubmitApprovalDecision(decision, comment) ? <small className="field-error">{t("rejectionReasonError")}</small> : null}<div className="modal-actions"><button className="action-button secondary" onClick={closeDecision} type="button">{t("cancel")}</button><button className={`action-button${decision === "reject" ? " danger" : ""}`} disabled={submittingDecision || !canSubmitApprovalDecision(decision, comment)} onClick={() => { void submitDecision(); }} type="button">{decision === "approve" ? t("approvalConfirmApprove") : t("approvalConfirmReject")}</button></div></section></div> : null}
    </AppShell>
  );
}
