"use client";

import { resourcePageTitle } from "@/lib/browserTitle";

import { scrollChatToEnd } from "@/lib/scrollChatToEnd";

import { UiValidationError } from "@/lib/transportError";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { type ChangeEvent, type FormEvent, type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ArrowRight, CheckCircle2, Database, Download, FileDown, FileText, MessageSquarePlus, Send, Upload, UserRound, X } from "lucide-react";
import { AppShell, StatusBadge } from "@/components/AppShell";
import { Modal } from "@/components/Modal";
import { useAuth } from "@/components/AuthProvider";
import { createProjectChatValidationRun, downloadProjectChatConversationCsv, getKnowledgeDetail, getProjectChatValidationRun, getProjectChatConversation, listProjectChatConversationPage, queryProjectChat, updateProjectChatFeedback, type KnowledgeDetailResponse, type ProjectChatConversationResponse, type ValidationRunResponse } from "@/lib/api";
import { ChatHistoryAuthor } from "@/components/ChatHistoryAuthor";
import { ChatRequestEpoch, chatConversationAccess, chatScopeRevoked, mergeChatHistory } from "@/lib/chatConversationAccess";
import { t as translate } from "@/lib/i18n";
import { formatShortDateTime as formatDateTime } from "@/lib/dateFormat";
import { useReadResource } from "@/lib/useReadResource";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

import { type Judgment, type AnswerEvaluation, type Translate, type ConversationEntry, validationEntries, parseCsv, downloadTextFile, retrievalErrorMessage } from "@/components/documentChat/documentChatModel";
import { AssistantMessage } from "@/components/documentChat/AssistantMessage";

export default function ChatTestPage() {
  const params = useParams<{ id: string; knowledgeId: string }>();
  const { apiFetch, authReady, currentUser } = useAuth();
  const { locale, format, localize, localizeKnown } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const extractionHref = `/project/${params.id}/knowledge/${params.knowledgeId}`;
  const submitReviewHref = `/project/${params.id}/knowledge/${params.knowledgeId}/submit-review`;
  const [detail, setDetail] = useState<KnowledgeDetailResponse | null>(null);
  const [titleRead, setTitleRead] = useState<{ fetch: typeof apiFetch; route: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [conversationEntries, setConversationEntries] = useState<ConversationEntry[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [histories, setHistories] = useState<ProjectChatConversationResponse[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [batchDisplay, setBatchDisplay] = useState(false);
  const [activeValidationRun, setActiveValidationRun] = useState<ValidationRunResponse | null>(null);
  const [batchCreating, setBatchCreating] = useState(false);
  const batchCreateInFlight = useRef(false);
  const scopeEpoch = useRef(new ChatRequestEpoch());
  const selectionEpoch = useRef(new ChatRequestEpoch());
  const [evaluations, setEvaluations] = useState<Record<string, AnswerEvaluation>>({});
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadQuestions, setUploadQuestions] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState("");
  const [batchCompletedCount, setBatchCompletedCount] = useState<number | null>(null);
  const chatThreadRef = useRef<HTMLDivElement>(null);
  const versionId = detail?.version.id;
  const latestConversationEntry = conversationEntries[conversationEntries.length - 1];
  const queryBusy = conversationEntries.some((entry) => entry.loading);
  const activeHistory = histories.find((item) => item.id === activeConversationId);
  const access = chatConversationAccess(activeHistory, currentUser?.user_id);
  const canContinue = authReady && historyReady && !loadError && !batchDisplay && Boolean(versionId)
    && detail?.chat_access?.mode === "staging" && detail.chat_access.query_enabled
    && (!activeConversationId || access.canContinue);
  const otherConversation = Boolean(activeConversationId && !access.isMine);
  const authorName = (activeConversationId ? activeHistory?.created_by_display_name : currentUser?.display_name)?.trim() || t("chatAuthorNameMissing");

  const selectConversation = useCallback((item: ProjectChatConversationResponse | null) => {
    setBatchDisplay(false);
    setActiveValidationRun(null);
    selectionEpoch.current.invalidate();
    setActiveConversationId(item?.id ?? null);
    setConversationEntries((item?.records ?? []).map((record) => ({ id: record.id, recordId: record.id,
      question: record.question, answer: record.answer ?? undefined, askedAt: record.asked_at,
      answeredAt: record.answered_at, citations: record.citations,
      status: record.answer ? "answered" : "no_answer" })));
    setEvaluations(Object.fromEntries((item?.records ?? []).filter((record) => record.evaluation !== "not_evaluated")
      .map((record) => [record.id, { judgment: record.evaluation === "correct" ? "correct" : "needs_revision", suggestion: record.revision_suggestion ?? "" }])));
    setQuestion("");
    setUploadOpen(false);
    setUploadError("");
    setBatchCompletedCount(null);
  }, []);

  // OPT424-035: the document detail and its first history page are one read resource bound to the route
  // and user. Starting a read resets the page as before; the result feeds the conversation state that
  // questions, history paging and scope revocation also update.
  const readChat = useCallback(async (signal: AbortSignal) => {
    const loaded = await getKnowledgeDetail(apiFetch, params.id, params.knowledgeId, signal);
    const page = await listProjectChatConversationPage(apiFetch, params.id, { scope_mode: "document_staging", document_version_id: loaded.version.id, signal });
    return { loaded, page };
  }, [apiFetch, params.id, params.knowledgeId]);
  useReadResource(readChat, JSON.stringify([params.id, params.knowledgeId, currentUser?.user_id ?? null]), authReady, {
    onStart: () => {
      scopeEpoch.current.invalidate();
      selectionEpoch.current.invalidate();
      setBatchDisplay(false);
      setActiveValidationRun(null);
      setBatchCreating(false);
      setHistoryReady(false);
      setHistoryBusy(false);
      setHistories([]);
      setHistoryCursor(null);
      setDetail(null);
      setConversationEntries([]);
      setActiveConversationId(null);
      setEvaluations({});
      setQuestion("");
      setUploadOpen(false);
      setLoadError(null);
    },
    onData: ({ loaded, page }) => {
      setDetail(loaded);
      setTitleRead({ fetch: apiFetch, route: JSON.stringify([params.id, params.knowledgeId]) });
      setHistories(page.items);
      setHistoryCursor(page.next_cursor);
      setHistoryReady(true);
      selectConversation(page.items[0] ?? null);
    },
    onError: (error) => {
      if (chatScopeRevoked(error)) setDetail(null);
      setLoadError(operationalErrorMessage(error, t, format, "documentChatLoadFailed"));
    },
  });

  async function loadMoreHistory() {
    if (!versionId || !historyCursor || historyBusy) return;
    const scope = scopeEpoch.current.capture();
    setHistoryBusy(true);
    try {
      const page = await listProjectChatConversationPage(apiFetch, params.id, { scope_mode: "document_staging", document_version_id: versionId, cursor: historyCursor });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setHistories((current) => mergeChatHistory(current, page.items));
      setHistoryCursor(page.next_cursor);
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope)) setLoadError(operationalErrorMessage(error, t, format, "documentChatLoadFailed"));
    } finally {
      if (scopeEpoch.current.isCurrent(scope)) setHistoryBusy(false);
    }
  }

  const discardRevokedScope = useCallback((error: unknown) => {
    if (!chatScopeRevoked(error)) return false;
    scopeEpoch.current.invalidate();
    selectConversation(null);
    setHistories([]);
    setHistoryCursor(null);
    setHistoryBusy(false);
    setDetail(null);
    setHistoryReady(false);
    setLoadError(operationalErrorMessage(error, t, format));
    return true;
  }, [format, selectConversation, t]);

  useEffect(() => {
    if (!chatThreadRef.current || !conversationEntries.length) return;
    scrollChatToEnd(chatThreadRef.current);
  }, [
    conversationEntries.length,
    latestConversationEntry?.answer,
    latestConversationEntry?.citations.length,
    latestConversationEntry?.error,
    latestConversationEntry?.loading
  ]);

  const validationRunId = activeValidationRun?.id;
  const validationRunning = Boolean(activeValidationRun && ["queued", "running"].includes(activeValidationRun.status));
  // OPT424-035: a running validation run is a read resource polled every 2.5 s until it finishes. A
  // result commits only while the scope and conversation selection that started the read are current.
  const pollGuards = useRef<{ scope: number; selection: number } | null>(null);
  const readValidationRun = useCallback(async (signal: AbortSignal) => {
    const run = await getProjectChatValidationRun(apiFetch, params.id, validationRunId!, signal);
    if (run.id !== validationRunId || run.project_id !== params.id || run.run_scope !== "document_staging"
      || run.selected_document_ids.length !== 1 || run.selected_document_ids[0] !== versionId) throw new Error("validation_scope_mismatch");
    return run;
  }, [apiFetch, params.id, validationRunId, versionId]);
  const pollCurrent = () => pollGuards.current !== null && scopeEpoch.current.isCurrent(pollGuards.current.scope) && selectionEpoch.current.isCurrent(pollGuards.current.selection);
  useReadResource(readValidationRun, validationRunId ?? null, Boolean(authReady && versionId && validationRunId && validationRunning), {
    poll: (outcome) => "data" in outcome && ["queued", "running"].includes(outcome.data.status) ? 2500 : null,
    onStart: () => { pollGuards.current = { scope: scopeEpoch.current.capture(), selection: selectionEpoch.current.capture() }; },
    onData: (run) => {
      if (!pollCurrent()) return;
      setActiveValidationRun(run);
      setConversationEntries(validationEntries(run, t, format));
      setBatchCompletedCount(run.completed_count + run.failed_count);
    },
    onError: (error) => {
      if (!pollCurrent() || discardRevokedScope(error)) return;
      const message = retrievalErrorMessage(error, t, format);
      setLoadError(message);
      setConversationEntries((entries) => entries.map((entry) => ({ ...entry, loading: false, error: message })));
    },
  });

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || !versionId || queryBusy || !canContinue) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    const conversationId = activeConversationId ?? crypto.randomUUID();
    const localId = `pending-${Date.now()}`;
    const askedAt = new Date().toISOString();
    setConversationEntries((entries) => [...entries, { id: localId, question: trimmedQuestion, askedAt, citations: [], loading: true }]);
    setQuestion("");
    try {
      const result = await queryProjectChat(apiFetch, params.id, { question: trimmedQuestion, document_version_ids: [versionId], scope_mode: "document_staging", conversation_id: conversationId, conversation_title: detail?.document.title ?? trimmedQuestion });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      if (selectionEpoch.current.isCurrent(selection)) {
      setActiveConversationId(result.conversation_id ?? conversationId);
      setConversationEntries((entries) => entries.map((entry) => entry.id === localId ? {
        ...entry,
        id: result.chat_record_id ?? localId,
        recordId: result.chat_record_id ?? undefined,
        answer: result.answer,
        answeredAt: new Date().toISOString(),
        citations: result.citations,
        loading: false,
        status: result.status
      } : entry));
      }
      const saved = await getProjectChatConversation(apiFetch, params.id, result.conversation_id ?? conversationId, { scope_mode: "document_staging", document_version_id: versionId });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setHistories((current) => mergeChatHistory(current, [saved]));
      if (selectionEpoch.current.isCurrent(selection)) selectConversation(saved);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      if (discardRevokedScope(error)) return;
      setConversationEntries((entries) => entries.map((entry) => entry.id === localId ? { ...entry, loading: false, error: retrievalErrorMessage(error, t, format) } : entry));
    }
  }

  function submitQuestionOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function startNewConversation() {
    selectConversation(null);
  }

  async function downloadConversationRecords() {
    if (!activeConversationId || !versionId || !access.canExport) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    try {
      const blob = await downloadProjectChatConversationCsv(apiFetch, params.id, activeConversationId, { scope_mode: "document_staging", document_version_id: versionId });
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `nomosmart-chat-test-${activeConversationId}.csv`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection) || discardRevokedScope(error)) return;
      setLoadError(operationalErrorMessage(error, t, format, "documentChatLoadFailed"));
    }
  }

  function downloadQuestionTemplate() {
    const template = "\uFEFFquestion,expected_answer,expected_keywords,selected_document_ids,category,priority\n"
      + `"${t("documentChatTemplateQuestion")}","","","","",""\n`;
    downloadTextFile(template, "nomosmart-chat-test-template.csv");
  }

  function openUploadModal() {
    if (!canContinue) return;
    setUploadFileName("");
    setUploadQuestions([]);
    setUploadError("");
    setBatchCompletedCount(null);
    setUploadOpen(true);
  }

  async function selectCsvFile(event: ChangeEvent<HTMLInputElement>) {
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    const file = event.target.files?.[0];
    setUploadQuestions([]);
    setUploadError("");
    setBatchCompletedCount(null);
    if (!file) {
      setUploadFileName("");
      return;
    }
    setUploadFileName(file.name);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadError(t("projectChatCsvOnly"));
      return;
    }
    try {
      const contents = await file.text();
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      const rows = parseCsv(contents);
      const headers = rows[0]?.map((header, index) => (index === 0 ? header.replace(/^\uFEFF/, "") : header).trim()) ?? [];
      const questionIndex = headers.indexOf("question");
      if (questionIndex < 0) throw new UiValidationError("projectChatCsvMissingQuestion");
      const questions = rows.slice(1).map((row) => row[questionIndex]?.trim() ?? "").filter(Boolean);
      if (!questions.length) throw new UiValidationError("projectChatCsvNoQuestions");
      setUploadQuestions(questions);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      setUploadError(error instanceof UiValidationError ? t(error.key) : error instanceof Error ? localizeKnown(error.message) ?? t("projectChatCsvParseFailed") : t("projectChatCsvParseFailed"));
    }
  }

  async function confirmBatchUpload() {
    if (!versionId || uploadQuestions.length === 0 || uploadError || queryBusy || !canContinue || batchCreateInFlight.current) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    batchCreateInFlight.current = true;
    setBatchCreating(true);
    try {
      const run = await createProjectChatValidationRun(apiFetch, params.id, {
        uploaded_file_name: uploadFileName || null,
        scope_mode: "document_staging",
        selected_document_version_ids: [versionId],
        questions: uploadQuestions.map((value) => ({ question: value, selected_document_ids: [versionId] }))
      });
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      // Validation items have independent Backend conversation IDs, not turns
      // belonging to the currently selected interactive conversation.
      setActiveConversationId(null);
      setBatchDisplay(true);
      setEvaluations({});
      setActiveValidationRun(run);
      setConversationEntries(validationEntries(run, t, format));
      setBatchCompletedCount(run.completed_count + run.failed_count);
      requestAnimationFrame(() => scrollChatToEnd(chatThreadRef.current));
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      if (discardRevokedScope(error)) return;
      setUploadError(operationalErrorMessage(error, t, format, "documentChatValidationCreateFailed"));
    } finally {
      batchCreateInFlight.current = false;
      if (scopeEpoch.current.isCurrent(scope) && selectionEpoch.current.isCurrent(selection)) setBatchCreating(false);
    }
  }

  async function recordEvaluation(entry: ConversationEntry, value: Judgment, suggestion = "") {
    if (!entry.recordId || !access.canEvaluate) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    try {
      const updated = await updateProjectChatFeedback(apiFetch, params.id, entry.recordId, { evaluation: value, revision_suggestion: suggestion || null });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setHistories((current) => current.map((item) => item.id === updated.conversation_id ? { ...item, records: item.records.map((record) => record.id === updated.id ? updated : record) } : item));
      if (selectionEpoch.current.isCurrent(selection)) setEvaluations((current) => ({ ...current, [entry.id]: { judgment: value, suggestion } }));
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope) && selectionEpoch.current.isCurrent(selection)) setLoadError(operationalErrorMessage(error, t, format));
    }
  }

  return (
    <AppShell title={t("chatTest")} browserTitle={resourcePageTitle(t("chatTest"), authReady && !loadError && titleRead?.fetch === apiFetch && titleRead.route === JSON.stringify([params.id, params.knowledgeId]) ? detail?.document.title : null, authReady && !loadError && titleRead?.fetch === apiFetch && titleRead.route === JSON.stringify([params.id, params.knowledgeId]) ? detail?.version.version_label : null)}>
      <div className="project-context chat-page-context">
        <Link className="text-link" href={extractionHref}><ArrowLeft size={16} /> {t("backToExtraction")}</Link>
        <span><Database size={14} /> {detail?.pipeline?.status === "submission_ready" ? t("stagingReady") : t("documentChatLiveVersionScope")}</span>
        <span>{detail?.version.version_label ?? t("documentChatLoadingVersion")}</span>
        <StatusBadge status={detail?.version.status ?? "processing"} />
        <div className="project-context-actions">
          <Link className="text-link next-stage-link" href={submitReviewHref}>{t("submitForReview")} <ArrowRight size={16} /></Link>
        </div>
      </div>

      <section className="chat-validation-shell">
        <aside className="chat-validation-sidebar">
          <div className="chat-sidebar-section chat-scope-settings">
            <p className="eyebrow">{t("referenceScope")}</p>
            <dl className="chat-scope-list">
              <div><dt>{t("currentDocumentVersion")}</dt><dd>{detail?.document.title ?? t("notificationLoading")} · {detail?.version.version_label ?? ""}</dd></div>
              <div><dt>{t("labelIndex")}</dt><dd>{t("documentChatStagingScopedIndex")}</dd></div>
              <div><dt>{t("labelChunks")}</dt><dd>{format("documentChatAvailableChunks", { count: detail?.chunks.length ?? 0 })}</dd></div>
            </dl>
            {loadError ? <FeedbackMessage tone="error">{localize(loadError)}</FeedbackMessage> : null}
            {detail?.chat_access?.mode === "published" ? <Link className="text-link" href={`/project/${params.id}/import?chat_version_id=${encodeURIComponent(detail.version.id)}`}>{t("knowledgePublishedChat")}</Link> : null}
            {detail && !canContinue && !activeConversationId && !loadError ? <p role="status">{t(detail.chat_access?.mode === "history_only" || detail.chat_access?.mode === "published" ? "knowledgeChatHistoryOnly" : "projectChatVectorIndexNotReady")}</p> : null}
          </div>

          <div className="chat-sidebar-section">
            <p className="eyebrow">{t("conversationHistory")}</p>
            <div aria-label={t("conversationHistory")} className="chat-document-history-list" role="region" tabIndex={0}>
            {histories.map((item) => {
              const itemAccess = chatConversationAccess(item, currentUser?.user_id);
              return <button aria-pressed={item.id === activeConversationId} className={`chat-history-item${item.id === activeConversationId ? " active" : ""}`} onClick={() => selectConversation(item)} key={item.id} type="button">
                <MessageSquarePlus size={16} />
                <span><strong>{item.title}</strong><ChatHistoryAuthor name={item.created_by_display_name} isMine={itemAccess.isMine} readOnly={!itemAccess.canContinue} />
                  <small>{format(item.message_count === 1 ? "documentChatTurnCountOne" : "documentChatTurnCountMany", { count: item.message_count })} · {formatDateTime(item.updated_at, locale)}</small></span>
              </button>;
            })}
            {historyCursor ? <button className="action-button secondary" disabled={historyBusy} onClick={() => void loadMoreHistory()} type="button">{t("chatHistoryLoadMore")}</button> : null}
            </div>
          </div>
        </aside>

        <div className="chat-conversation-panel">
          <header className="chat-conversation-header">
            <div><strong>{detail?.document.title ?? t("documentChatTitleFallback")}</strong><small>{t("documentChatScopeHelp")}</small></div>
            <div className="chat-conversation-header-actions">
              <button className="action-button secondary" disabled={!canContinue || queryBusy} onClick={openUploadModal} type="button"><Upload size={17} /> {t("uploadTestConversations")}</button>
              <button className="action-button secondary" disabled={!access.canExport || !conversationEntries.length} onClick={() => void downloadConversationRecords()} type="button"><Download size={17} /> {t("downloadConversation")}</button>
              <button className="action-button secondary" disabled={!historyReady} onClick={startNewConversation} type="button"><MessageSquarePlus size={17} /> {t("chatNewOwnConversation")}</button>
            </div>
          </header>
          <div className="chat-thread" aria-live="polite" ref={chatThreadRef}>
            {(activeConversationId || batchDisplay) && !canContinue ? <FeedbackMessage tone="info">{t(otherConversation ? "chatOtherConversationReadOnly" : "chatConversationWriteDenied")}</FeedbackMessage> : null}
            {activeValidationRun ? <p role="status"><StatusBadge status={activeValidationRun.status} /> {format("documentChatBatchProgress", { completed: activeValidationRun.completed_count, failed: activeValidationRun.failed_count, total: activeValidationRun.total_count })}</p> : null}
            {conversationEntries.length === 0 ? <div className="chat-empty-state"><MessageSquarePlus size={22} /><span>{t("emptyConversation")}</span></div> : null}
            {conversationEntries.map((entry) => (
              <div className="chat-response-pair" key={entry.id}>
                <article className="chat-message user-message"><div className="message-avatar"><UserRound size={17} /></div><div className="user-message-body"><small>{authorName}</small><p>{entry.question}</p></div></article>
                {entry.validationStatus ? <StatusBadge status={entry.validationStatus} /> : null}
                <AssistantMessage key={`${activeConversationId}-${entry.id}`} entry={entry} canEvaluate={access.canEvaluate} evaluation={evaluations[entry.id]} extractionHref={extractionHref} onEvaluate={recordEvaluation} />
              </div>
            ))}
          </div>

          <form aria-busy={queryBusy} className="chat-composer" onSubmit={submitQuestion}>
            <label htmlFor="chat-question">{t("askQuestion")}</label>
            <div><textarea disabled={!canContinue || queryBusy} id="chat-question" onChange={(event) => setQuestion(event.target.value)} onKeyDown={submitQuestionOnEnter} placeholder={t("chatPlaceholder")} rows={2} value={question} /><button aria-label={queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")} className="action-button" disabled={!question.trim() || !canContinue || queryBusy} type="submit"><Send size={17} /> {queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")}</button></div>
          </form>
        </div>
      </section>

      {uploadOpen ? (
        <Modal onEscape={() => setUploadOpen(false)} aria-labelledby="batch-chat-upload-title" className="modal-panel chat-small-modal batch-chat-modal">
            <div className="modal-header"><div><p className="eyebrow">{t("batchValidation")}</p><h2 id="batch-chat-upload-title">{t("uploadTestConversations")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={() => setUploadOpen(false)} type="button"><X size={18} /></button></div>
            {batchCompletedCount !== null ? <div className="batch-upload-complete"><CheckCircle2 size={24} /><div><strong>{t(validationRunning ? "documentChatBatchQueued" : "documentChatBatchFinished")}</strong><span>{activeValidationRun ? format("documentChatBatchProgress", { completed: activeValidationRun.completed_count, failed: activeValidationRun.failed_count, total: activeValidationRun.total_count }) : format("documentChatBatchCreated", { count: batchCompletedCount })}</span></div></div> : (
              <div className="batch-upload-body">
                <div className="batch-template-row"><div><strong>{t("csvTemplate")}</strong><small>question、expected_answer、expected_keywords、selected_document_ids、category、priority</small></div><button className="action-button secondary" onClick={downloadQuestionTemplate} type="button"><FileDown size={16} /> {t("downloadTemplate")}</button></div>
                <label className="csv-upload-field"><Upload size={22} /><span><strong>{t("selectCsvFile")}</strong><small>.csv · UTF-8</small></span><input accept=".csv,text/csv" onChange={selectCsvFile} type="file" /></label>
                {uploadFileName ? <div className="batch-file-status"><FileText size={17} /><span><strong>{uploadFileName}</strong><small>{uploadError ? localize(uploadError) : format("documentChatValidQuestionCount", { count: uploadQuestions.length })}</small></span></div> : null}
                {uploadError ? <FeedbackMessage tone="error">{localize(uploadError)}</FeedbackMessage> : null}
                {uploadQuestions.length ? <ol className="batch-question-preview">{uploadQuestions.slice(0, 3).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}{uploadQuestions.length > 3 ? <li>{format("projectChatMoreQuestions", { count: uploadQuestions.length - 3 })}</li> : null}</ol> : null}
              </div>
            )}
            <div className="modal-actions"><button className="action-button secondary" onClick={() => setUploadOpen(false)} type="button">{batchCompletedCount !== null ? t("closeDialog") : t("cancel")}</button>{batchCompletedCount === null ? <button className="action-button" disabled={!uploadQuestions.length || Boolean(uploadError) || batchCreating} onClick={confirmBatchUpload} type="button">{t("confirmUpload")}</button> : null}</div>
          </Modal>
      ) : null}
    </AppShell>
  );
}
