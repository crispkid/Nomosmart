"use client";

import { type ChangeEvent, type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, ArrowRight, Bot, CheckCircle2, Clock3, Database, Download, FileDown, FileText, MessageSquarePlus, Send, Upload, UserRound, Wrench, X } from "lucide-react";
import { AppShell, StatusBadge } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { ChatWaitingIndicator } from "@/components/ChatWaitingIndicator";
import { createProjectChatValidationRun, downloadProjectChatConversationCsv, getKnowledgeDetail, getProjectChatConversation, listProjectChatConversationPage, queryProjectChat, updateProjectChatFeedback, type KnowledgeDetailResponse, type ProjectChatCitation, type ProjectChatConversationResponse } from "@/lib/api";
import { ChatHistoryAuthor } from "@/components/ChatHistoryAuthor";
import { ChatRequestEpoch, chatConversationAccess, chatScopeRevoked, mergeChatHistory } from "@/lib/chatConversationAccess";
import { t as translate } from "@/lib/i18n";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";

type Judgment = "correct" | "needs_revision";
type AnswerEvaluation = { judgment: Judgment; suggestion: string };
type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;
type ConversationEntry = {
  id: string;
  recordId?: string;
  question: string;
  answer?: string;
  askedAt: string;
  answeredAt?: string | null;
  citations: ProjectChatCitation[];
  loading?: boolean;
  error?: string;
  status?: "answered" | "no_answer";
};

function parseCsv(text: string, t: Translate) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (inQuotes) {
      if (character === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') inQuotes = false;
      else cell += character;
      continue;
    }
    if (character === '"') inQuotes = true;
    else if (character === ",") {
      row.push(cell);
      cell = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else cell += character;
  }
  if (inQuotes) throw new Error(t("projectChatCsvUnclosedQuote"));
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function downloadTextFile(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function retrievalErrorMessage(error: unknown, t: Translate, format: Format) {
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code?: unknown }).code) : "";
  if (code === "embedding_provider_required" || code === "embedding_model_required" || code === "embedding_adapter_credential_required" || code === "embedding_adapter_secret_ref_unresolved") return t("projectChatEmbeddingProviderRequired");
  if (code === "query_embedding_failed" || code === "embedding_adapter_unavailable" || code === "embedding_adapter_provider_rejected" || code === "embedding_response_invalid") return t("projectChatQueryEmbeddingFailed");
  if (code === "vector_index_not_ready" || code === "embedding_profile_required") return t("projectChatVectorIndexNotReady");
  if (code === "embedding_profile_mismatch") return t("projectChatEmbeddingProfileMismatch");
  if (code === "hybrid_retrieval_failed" || code === "opensearch_retrieval_unavailable") return t("projectChatOpenSearchUnavailable");
  if (code === "retrieval_scope_inconsistent") return t("projectChatRetrievalScopeInconsistent");
  if (code === "provider_response_contract_invalid") return t("chatCitationProviderMismatch");
  return operationalErrorMessage(error, t, format, "documentChatQueryFailed");
}

function formatDateTime(value: string | null | undefined, locale: "en" | "zh") {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "en" ? "en-US" : "zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function ChatTestPage() {
  const params = useParams<{ id: string; knowledgeId: string }>();
  const { apiFetch, authReady, currentUser } = useAuth();
  const { locale, format, localize, localizeKnown } = useI18n();
  const t = useMemo<Translate>(() => (key) => translate(key, locale), [locale]);
  const extractionHref = `/project/${params.id}/knowledge/${params.knowledgeId}`;
  const submitReviewHref = `/project/${params.id}/knowledge/${params.knowledgeId}/submit-review`;
  const [detail, setDetail] = useState<KnowledgeDetailResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [conversationEntries, setConversationEntries] = useState<ConversationEntry[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [histories, setHistories] = useState<ProjectChatConversationResponse[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [batchDisplay, setBatchDisplay] = useState(false);
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
  const canContinue = authReady && historyReady && !loadError && !batchDisplay && Boolean(versionId) && (!activeConversationId || access.canContinue);
  const otherConversation = Boolean(activeConversationId && !access.isMine);
  const authorName = (activeConversationId ? activeHistory?.created_by_display_name : currentUser?.display_name)?.trim() || t("chatAuthorNameMissing");

  function selectConversation(item: ProjectChatConversationResponse | null) {
    setBatchDisplay(false);
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
  }

  useEffect(() => {
    const scopeGuard = scopeEpoch.current;
    const selectionGuard = selectionEpoch.current;
    scopeGuard.invalidate();
    selectionGuard.invalidate();
    setBatchDisplay(false);
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
    if (!authReady) return;
    let cancelled = false;
    async function load() {
      try {
        const loaded = await getKnowledgeDetail(apiFetch, params.id, params.knowledgeId);
        if (cancelled) return;
        setDetail(loaded);
        const page = await listProjectChatConversationPage(apiFetch, params.id, { scope_mode: "document_staging", document_version_id: loaded.version.id });
        if (cancelled) return;
        setHistories(page.items);
        setHistoryCursor(page.next_cursor);
        setHistoryReady(true);
        selectConversation(page.items[0] ?? null);
      } catch (error) {
        if (!cancelled) {
          if (chatScopeRevoked(error)) setDetail(null);
          setLoadError(operationalErrorMessage(error, t, format, "documentChatLoadFailed"));
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
      scopeGuard.invalidate();
      selectionGuard.invalidate();
    };
  }, [apiFetch, authReady, currentUser?.user_id, format, params.id, params.knowledgeId, t]);

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

  function discardRevokedScope(error: unknown) {
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
  }

  useEffect(() => {
    if (!chatThreadRef.current || !conversationEntries.length) return;
    chatThreadRef.current.scrollTo({
      top: chatThreadRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, [
    conversationEntries.length,
    latestConversationEntry?.answer,
    latestConversationEntry?.citations.length,
    latestConversationEntry?.error,
    latestConversationEntry?.loading
  ]);

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
      const rows = parseCsv(contents, t);
      const headers = rows[0]?.map((header, index) => (index === 0 ? header.replace(/^\uFEFF/, "") : header).trim()) ?? [];
      const questionIndex = headers.indexOf("question");
      if (questionIndex < 0) throw new Error(t("projectChatCsvMissingQuestion"));
      const questions = rows.slice(1).map((row) => row[questionIndex]?.trim() ?? "").filter(Boolean);
      if (!questions.length) throw new Error(t("projectChatCsvNoQuestions"));
      setUploadQuestions(questions);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      setUploadError(error instanceof Error ? localizeKnown(error.message) ?? t("projectChatCsvParseFailed") : t("projectChatCsvParseFailed"));
    }
  }

  async function confirmBatchUpload() {
    if (!versionId || uploadQuestions.length === 0 || uploadError || queryBusy || !canContinue) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    try {
      const run = await createProjectChatValidationRun(apiFetch, params.id, {
        uploaded_file_name: uploadFileName || null,
        scope_mode: "document_staging",
        selected_document_version_ids: [versionId],
        questions: uploadQuestions.map((value) => ({ question: value, selected_document_ids: [versionId] }))
      });
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      const startedAt = Date.now();
      // Validation items have independent Backend conversation IDs, not turns
      // belonging to the currently selected interactive conversation.
      setActiveConversationId(null);
      setBatchDisplay(true);
      setEvaluations({});
      setConversationEntries(run.items.map((item, index) => ({
        id: item.chat_record_id ?? item.id,
        recordId: item.chat_record_id ?? undefined,
        question: item.question,
        answer: item.answer ?? undefined,
        askedAt: new Date(startedAt + index).toISOString(),
        answeredAt: item.status === "completed" ? new Date().toISOString() : null,
        citations: item.citations,
        loading: ["pending", "running"].includes(item.status),
        error: item.status === "error" ? operationalCodeMessage(item.error_code, t, format, "documentChatQueryFailed") : undefined,
        status: item.answer ? "answered" as const : undefined
      })));
      setBatchCompletedCount(run.items.length);
      requestAnimationFrame(() => chatThreadRef.current?.scrollTo({ behavior: "smooth", top: chatThreadRef.current.scrollHeight }));
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      if (discardRevokedScope(error)) return;
      setUploadError(operationalErrorMessage(error, t, format, "documentChatValidationCreateFailed"));
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
    <AppShell title={t("chatTest")}>
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
            {loadError ? <div className="batch-upload-error">{localize(loadError)}</div> : null}
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
            {(activeConversationId || batchDisplay) && !canContinue ? <p role="status" className="chat-readonly-notice">{t(otherConversation ? "chatOtherConversationReadOnly" : "chatConversationWriteDenied")}</p> : null}
            {conversationEntries.length === 0 ? <div className="chat-empty-state"><MessageSquarePlus size={22} /><span>{t("emptyConversation")}</span></div> : null}
            {conversationEntries.map((entry) => (
              <div className="chat-response-pair" key={entry.id}>
                <article className="chat-message user-message"><div className="message-avatar"><UserRound size={17} /></div><div className="user-message-body"><small>{authorName}</small><p>{entry.question}</p></div></article>
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
        <div className="modal-backdrop" role="presentation">
          <section aria-labelledby="batch-chat-upload-title" aria-modal="true" className="modal-panel chat-small-modal batch-chat-modal" role="dialog">
            <div className="modal-header"><div><p className="eyebrow">{t("batchValidation")}</p><h2 id="batch-chat-upload-title">{t("uploadTestConversations")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={() => setUploadOpen(false)} type="button"><X size={18} /></button></div>
            {batchCompletedCount !== null ? <div className="batch-upload-complete"><CheckCircle2 size={24} /><div><strong>{t("batchCompleted")}</strong><span>{format("documentChatBatchCreated", { count: batchCompletedCount })}</span></div></div> : (
              <div className="batch-upload-body">
                <div className="batch-template-row"><div><strong>{t("csvTemplate")}</strong><small>question、expected_answer、expected_keywords、selected_document_ids、category、priority</small></div><button className="action-button secondary" onClick={downloadQuestionTemplate} type="button"><FileDown size={16} /> {t("downloadTemplate")}</button></div>
                <label className="csv-upload-field"><Upload size={22} /><span><strong>{t("selectCsvFile")}</strong><small>.csv · UTF-8</small></span><input accept=".csv,text/csv" onChange={selectCsvFile} type="file" /></label>
                {uploadFileName ? <div className="batch-file-status"><FileText size={17} /><span><strong>{uploadFileName}</strong><small>{uploadError ? localize(uploadError) : format("documentChatValidQuestionCount", { count: uploadQuestions.length })}</small></span></div> : null}
                {uploadError ? <div className="batch-upload-error">{localize(uploadError)}</div> : null}
                {uploadQuestions.length ? <ol className="batch-question-preview">{uploadQuestions.slice(0, 3).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}{uploadQuestions.length > 3 ? <li>{format("projectChatMoreQuestions", { count: uploadQuestions.length - 3 })}</li> : null}</ol> : null}
              </div>
            )}
            <div className="modal-actions"><button className="action-button secondary" onClick={() => setUploadOpen(false)} type="button">{batchCompletedCount !== null ? t("closeDialog") : t("cancel")}</button>{batchCompletedCount === null ? <button className="action-button" disabled={!uploadQuestions.length || Boolean(uploadError)} onClick={confirmBatchUpload} type="button">{t("confirmUpload")}</button> : null}</div>
          </section>
        </div>
      ) : null}
    </AppShell>
  );
}

function AssistantMessage({ entry, canEvaluate, evaluation, extractionHref, onEvaluate }: { entry: ConversationEntry; canEvaluate: boolean; evaluation?: AnswerEvaluation; extractionHref: string; onEvaluate: (entry: ConversationEntry, value: Judgment, suggestion?: string) => Promise<void> }) {
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
        {entry.loading ? <ChatWaitingIndicator label={t("documentChatQueryingStaging")} /> : entry.error ? <p className="field-error">{localize(entry.error)}</p> : (
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
        <div className="modal-backdrop" role="presentation">
          <section aria-labelledby={`${entry.id}-revision-title`} aria-modal="true" className="modal-panel chat-small-modal" role="dialog">
            <div className="modal-header"><div><p className="eyebrow">{t("answerNeedsRevision")}</p><h2 id={`${entry.id}-revision-title`}>{t("revisionSuggestion")}</h2></div><button aria-label={t("closeDialog")} className="icon-button" onClick={() => setRevisionOpen(false)} type="button"><X size={18} /></button></div>
            <form className="revision-suggestion-form" onSubmit={submitRevision}><label htmlFor={`${entry.id}-revision`}>{t("revisionSuggestion")}</label><textarea autoFocus id={`${entry.id}-revision`} onChange={(event) => setRevisionSuggestion(event.target.value)} placeholder={t("revisionPlaceholder")} required rows={5} value={revisionSuggestion} /><div className="modal-actions"><button className="action-button secondary" onClick={() => setRevisionOpen(false)} type="button">{t("cancel")}</button><button className="action-button" disabled={!revisionSuggestion.trim()} type="submit">{t("saveSuggestion")}</button></div></form>
          </section>
        </div>
      ) : null}
    </article>
  );
}
