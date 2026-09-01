"use client";

import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Check, CheckCircle2, ChevronDown, ChevronRight, Download, FileDown, FileText, MessageSquarePlus, Search, Send, Trash2, Upload, UserRound, Wrench, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { ChatResponseEvidence } from "@/components/ChatResponseEvidence";
import { ChatWaitingIndicator } from "@/components/ChatWaitingIndicator";
import { createProjectChatValidationRun, deleteProjectChatConversation, downloadProjectChatConversationCsv, getProjectChatValidationRun, getProjectServingStatus, listProjectChatConversations, listProjectDocuments, queryProjectChat, retryFailedProjectChatValidationItems, updateProjectChatFeedback, type ProjectChatCitation, type ProjectChatConversationResponse, type ProjectServingStatusResponse, type ValidationRunResponse } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";

type ChatDocument = { id: string; documentId: string; title: string; version: string; source: string; chunks: number; documentStatus: string; versionStatus: string };
type Entry = { id: number; recordId?: string; validationItemId?: string; question: string; answer?: string; citations?: ProjectChatCitation[]; loading?: boolean; error?: string; status?: "answered" | "no_answer"; retrievalStrategy?: string };
type Judgment = "correct" | "revision";
type CsvValidationQuestion = {
  question: string;
  expected_answer?: string | null;
  expected_keywords?: string[];
  selected_document_ids?: string[];
  category?: string | null;
  priority?: string | null;
};
type ProjectConversation = {
  id: string;
  scopeIds: string[];
  entries: Entry[];
  judgments: Record<number, Judgment>;
  createdAt: number;
  updatedAt: number;
  persisted?: boolean;
};

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, values: Record<string, string | number>) => string;

function parseCsv(text: string, t: Translate) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') { cell += '"'; index += 1; }
      else if (character === '"') quoted = false;
      else cell += character;
    } else if (character === '"') quoted = true;
    else if (character === ",") { row.push(cell); cell = ""; }
    else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = []; cell = "";
    } else cell += character;
  }
  if (quoted) throw new Error(t("projectChatCsvUnclosedQuote"));
  row.push(cell);
  if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function downloadCsv(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function retrievalErrorMessage(error: unknown, t: Translate, format: Format) {
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code?: unknown }).code) : "";
  if (code === "active_manifest_required") return t("projectChatActiveManifestRequired");
  if (code === "retrieval_scope_denied") return t("projectChatRetrievalScopeDenied");
  if (code === "published_index_not_ready") return t("projectChatPublishedIndexNotReady");
  if (code === "opensearch_retrieval_unavailable" || code === "hybrid_retrieval_failed") return t("projectChatOpenSearchUnavailable");
  if (code === "retrieval_scope_inconsistent") return t("projectChatRetrievalScopeInconsistent");
  if (code === "embedding_provider_required" || code === "embedding_model_required" || code === "embedding_adapter_credential_required" || code === "embedding_adapter_secret_ref_unresolved") return t("projectChatEmbeddingProviderRequired");
  if (code === "query_embedding_failed" || code === "embedding_adapter_unavailable" || code === "embedding_adapter_provider_rejected" || code === "embedding_response_invalid") return t("projectChatQueryEmbeddingFailed");
  if (code === "vector_index_not_ready" || code === "embedding_profile_required") return t("projectChatVectorIndexNotReady");
  if (code === "embedding_profile_mismatch") return t("projectChatEmbeddingProfileMismatch");
  if (code === "citation_scope_mismatch") return t("projectChatCitationScopeMismatch");
  if (code === "provider_response_contract_invalid") return t("chatCitationProviderMismatch");
  return operationalErrorMessage(error, t, format, "projectChatRetrievalFailed");
}

function retrievalLabel(strategy?: string) {
  if (strategy === "hybrid") return "Hybrid Retrieval";
  if (strategy === "vector") return "Vector Retrieval";
  if (strategy === "keyword") return "Keyword Retrieval";
  return "Live RAG";
}

function newConversationId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `conversation-${Date.now()}`;
}

function isUuid(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function sameScopeIds(left: string[], right: string[]) {
  return left.length === right.length && left.slice().sort().join() === right.slice().sort().join();
}

function timestamp(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function conversationFromHistory(item: ProjectChatConversationResponse): ProjectConversation {
  const entries = item.records.map((record) => ({
    id: timestamp(record.asked_at),
    recordId: record.id,
    question: record.question,
    answer: record.answer ?? undefined,
    citations: record.citations,
    status: record.answer ? "answered" as const : "no_answer" as const
  }));
  const judgmentEntries = item.records.flatMap((record): [number, Judgment][] => {
    if (record.evaluation === "needs_revision") return [[timestamp(record.asked_at), "revision"]];
    if (record.evaluation === "correct") return [[timestamp(record.asked_at), "correct"]];
    return [];
  });
  const updatedAt = timestamp(item.updated_at);
  return {
    id: item.id,
    scopeIds: item.selected_document_version_ids,
    entries,
    judgments: Object.fromEntries(judgmentEntries) as Record<number, Judgment>,
    createdAt: updatedAt,
    updatedAt,
    persisted: true
  };
}

function validationItemMessage(status: string, answer: string | null | undefined, t: Translate) {
  if (answer) return answer;
  if (status === "running") return t("projectChatValidationRunning");
  if (status === "error") return t("projectChatValidationFailed");
  if (status === "failed") return t("projectChatValidationFailedScore");
  if (status === "needs_review") return t("projectChatValidationNeedsReview");
  if (status === "completed" || status === "passed") return t("projectChatValidationCompletedNoAnswer");
  return t("projectChatValidationQueued");
}

export function ProjectChatTest() {
  const params = useParams<{ id?: string }>();
  const { apiFetch, authReady } = useAuth();
  const { t, format, localize, localizeKnown } = useI18n();
  const [documents, setDocuments] = useState<ChatDocument[]>([]);
  const [documentSource, setDocumentSource] = useState<"loading" | "live" | "empty" | "error">("loading");
  const [servingStatus, setServingStatus] = useState<ProjectServingStatusResponse | null>(null);
  const servingReadyIds = useMemo(() => new Set((servingStatus?.documents ?? []).filter((document) => document.index_ready).map((document) => document.document_version_id)), [servingStatus]);
  const eligibleIds = useMemo(() => documents.filter((document) => document.documentStatus === "active" && document.versionStatus === "active" && servingReadyIds.has(document.id)).map((document) => document.id), [documents, servingReadyIds]);
  const allIds = eligibleIds;
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [conversations, setConversations] = useState<ProjectConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [historyStatus, setHistoryStatus] = useState<"loading" | "ready" | "error">("loading");
  const [historyError, setHistoryError] = useState("");
  const [query, setQuery] = useState("");
  const [question, setQuestion] = useState("");
  const [revisionEntryId, setRevisionEntryId] = useState<number | null>(null);
  const [revisionText, setRevisionText] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadQuestions, setUploadQuestions] = useState<CsvValidationQuestion[]>([]);
  const [uploadError, setUploadError] = useState("");
  const [uploadDragging, setUploadDragging] = useState(false);
  const [batchCompletedCount, setBatchCompletedCount] = useState<number | null>(null);
  const [activeValidationRun, setActiveValidationRun] = useState<ValidationRunResponse | null>(null);
  const [servingExpanded, setServingExpanded] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const chatThreadRef = useRef<HTMLDivElement>(null);
  const activeConversation = activeConversationId ? conversations.find((conversation) => conversation.id === activeConversationId) ?? null : null;
  const scopeIds = activeConversation?.scopeIds ?? selectedIds;
  const entries = activeConversation?.entries ?? [];
  const queryBusy = entries.some((entry) => entry.loading);
  const latestEntry = entries[entries.length - 1];
  const judgments = activeConversation?.judgments ?? {};
  const filtered = useMemo(() => documents.filter((document) => document.title.toLowerCase().includes(query.toLowerCase())), [documents, query]);
  const scopeDirty = activeConversation ? !sameScopeIds(selectedIds, activeConversation.scopeIds) : false;
  const orderedConversations = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);
  const persistedConversationCount = conversations.filter((conversation) => conversation.persisted).length;
  const allSelected = allIds.length > 0 && selectedIds.length === allIds.length && allIds.every((id) => selectedIds.includes(id));
  const allScopeIdsFormal = scopeIds.every((id) => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(id));
  const allScopeIdsEligible = scopeIds.length > 0 && scopeIds.every((id) => eligibleIds.includes(id));
  const validationRunning = activeValidationRun ? ["queued", "running"].includes(activeValidationRun.status) : false;
  const validationFinished = activeValidationRun ? ["completed", "partial_failed", "failed", "cancelled"].includes(activeValidationRun.status) : batchCompletedCount !== null;
  const canRetryFailedValidation = activeValidationRun ? ["partial_failed", "failed"].includes(activeValidationRun.status) && activeValidationRun.failed_count > 0 : false;
  const documentSourceLabel = documentSource === "live" ? t("projectChatSourceLive") : documentSource === "empty" ? t("projectChatSourceNoActiveManifest") : documentSource === "error" ? t("projectChatSourceUnavailable") : t("projectChatSourceLoading");
  const servingReadinessLabel = servingStatus?.readiness === "ready" ? t("projectChatServingReady") : servingStatus?.readiness === "partial" ? t("projectChatServingPartial") : servingStatus?.readiness === "empty" ? t("projectChatServingEmpty") : t("projectChatServingLoading");
  const unavailableVersionLabel = t("projectChatUnavailableVersion");

  useEffect(() => {
    const projectId = params?.id;
    if (!authReady || !projectId) return;
    let cancelled = false;
    Promise.all([listProjectDocuments(apiFetch, projectId), getProjectServingStatus(apiFetch, projectId)]).then(([items, status]) => {
      if (cancelled) return;
      setServingStatus(status);
      const chatDocuments = items
        .map((item) => {
          const versionId = item.latest_version?.id ?? item.id;
          const servingDocument = status.documents.find((document) => document.document_version_id === versionId);
          return {
            id: versionId,
            documentId: item.id,
            title: item.title,
            version: item.latest_version?.version_label ?? unavailableVersionLabel,
            source: item.source_type,
            chunks: servingDocument?.chunk_count ?? 0,
            documentStatus: item.status,
            versionStatus: item.latest_version?.status ?? "missing"
          };
        });
      const eligibleDocuments = chatDocuments.filter((document) => document.documentStatus === "active" && document.versionStatus === "active" && status.documents.some((servingDocument) => servingDocument.document_version_id === document.id && servingDocument.index_ready));
      if (chatDocuments.length) {
        setDocuments(chatDocuments);
        setSelectedIds(eligibleDocuments.map((item) => item.id));
        setDocumentSource(eligibleDocuments.length ? "live" : "empty");
      } else {
        setDocuments([]);
        setSelectedIds([]);
        setDocumentSource("empty");
      }
    }).catch(() => {
      if (!cancelled) {
        setServingStatus(null);
        setDocuments([]);
        setSelectedIds([]);
        setDocumentSource("error");
      }
    });
    return () => { cancelled = true; };
  }, [apiFetch, authReady, params?.id, unavailableVersionLabel]);

  useEffect(() => {
    const projectId = params?.id;
    if (!authReady || !projectId) return;
    let cancelled = false;
    setHistoryStatus("loading");
    setHistoryError("");
    listProjectChatConversations(apiFetch, projectId).then((history) => {
      if (cancelled) return;
      setHistoryStatus("ready");
      setHistoryError("");
      if (history.length) {
        const restored = history.map(conversationFromHistory);
        setConversations(restored);
        setActiveConversationId(restored[0].id);
      } else {
        setConversations([]);
        setActiveConversationId(null);
      }
    }).catch((error) => {
      if (cancelled) return;
      setConversations([]);
      setActiveConversationId(null);
      setHistoryStatus("error");
      setHistoryError(operationalErrorMessage(error, t, format, "projectChatHistoryLoadFailed"));
    });
    return () => { cancelled = true; };
  }, [apiFetch, authReady, format, params?.id, t]);

  useEffect(() => {
    if (!chatThreadRef.current || !entries.length) return;
    chatThreadRef.current.scrollTo({
      top: chatThreadRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, [
    activeConversationId,
    entries.length,
    latestEntry?.answer,
    latestEntry?.citations?.length,
    latestEntry?.error,
    latestEntry?.loading
  ]);

  useEffect(() => {
    if (!authReady || !params?.id || !activeValidationRun || !validationRunning) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      getProjectChatValidationRun(apiFetch, params.id!, activeValidationRun.id).then((run) => {
        if (cancelled) return;
        setActiveValidationRun(run);
        setBatchCompletedCount(run.completed_count + run.failed_count);
        setConversations((current) => current.map((conversation) => conversation.id === activeConversationId ? {
          ...conversation,
          entries: conversation.entries.map((entry) => {
            if (!entry.validationItemId) return entry;
            const item = run.items.find((candidate) => candidate.id === entry.validationItemId);
            if (!item) return entry;
            return {
              ...entry,
              recordId: item.chat_record_id ?? entry.recordId,
              answer: validationItemMessage(item.status, item.answer, t),
              citations: item.citations,
              loading: ["pending", "running"].includes(item.status),
              error: item.status === "error" ? operationalCodeMessage(item.error_code, t, format, "projectChatRetrievalFailed") : undefined,
              status: item.answer ? "answered" as const : undefined
            };
          }),
          updatedAt: Date.now()
        } : conversation));
      }).catch((error) => {
        if (cancelled) return;
        setConversations((current) => current.map((conversation) => conversation.id === activeConversationId ? { ...conversation, entries: conversation.entries.map((entry) => entry.validationItemId ? { ...entry, loading: false, error: retrievalErrorMessage(error, t, format) } : entry), updatedAt: Date.now() } : conversation));
      });
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeConversationId, activeValidationRun, apiFetch, authReady, format, params?.id, t, validationRunning]);

  function toggleDocument(id: string) {
    if (!eligibleIds.includes(id)) return;
    setSelectedIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  function isDocumentEligible(document: ChatDocument) {
    return eligibleIds.includes(document.id);
  }

  function documentDisabledLabel(document: ChatDocument) {
    if (document.documentStatus === "inactive") return t("projectChatDocumentInactive");
    if (document.documentStatus === "deleted") return t("projectChatDocumentDeleted");
    if (document.versionStatus !== "active") return t("projectChatDocumentNotPublished");
    return t("projectChatDocumentIndexNotReady");
  }

  function updateActiveConversation(update: (conversation: ProjectConversation) => ProjectConversation) {
    if (!activeConversationId) return;
    setConversations((current) => current.map((conversation) => conversation.id === activeConversationId ? update(conversation) : conversation));
  }

  function startScopedConversation() {
    if (!selectedIds.length || queryBusy) return;
    const existingDraft = conversations.find((conversation) => !conversation.persisted && !conversation.entries.length && sameScopeIds(conversation.scopeIds, selectedIds));
    if (existingDraft) {
      activateConversation(existingDraft);
      return;
    }
    const now = Date.now();
    const conversation: ProjectConversation = { id: newConversationId(), scopeIds: [...selectedIds], entries: [], judgments: {}, createdAt: now, updatedAt: now };
    setConversations((current) => [conversation, ...current]);
    setActiveConversationId(conversation.id);
    setQuestion("");
  }

  function activateConversation(conversation: ProjectConversation) {
    setActiveConversationId(conversation.id);
    setSelectedIds(conversation.scopeIds.filter((id) => eligibleIds.includes(id)));
    setQuestion("");
  }

  async function confirmDeleteConversation() {
    if (!deleteTargetId || deleteBusy) return;
    const target = conversations.find((conversation) => conversation.id === deleteTargetId);
    if (!target) {
      setDeleteTargetId(null);
      return;
    }
    setDeleteBusy(true);
    setDeleteError("");
    try {
      if (params?.id && isUuid(target.id) && target.persisted) {
        await deleteProjectChatConversation(apiFetch, params.id, target.id);
      }
      const remaining = conversations.filter((conversation) => conversation.id !== target.id);
      if (remaining.length) {
        const nextActive = [...remaining].sort((a, b) => b.updatedAt - a.updatedAt)[0];
        setConversations(remaining);
        if (target.id === activeConversationId) activateConversation(nextActive);
      } else {
        setConversations([]);
        setActiveConversationId(null);
        if (!selectedIds.length && allIds.length) setSelectedIds(allIds);
      }
      setDeleteTargetId(null);
    } catch (error) {
      setDeleteError(operationalErrorMessage(error, t, format, "projectChatDeleteFailed"));
    } finally {
      setDeleteBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || !scopeIds.length || scopeDirty || queryBusy) return;
    const now = Date.now();
    const text = question.trim();
    const localConversationId = activeConversation?.id ?? newConversationId();
    const localScopeIds = [...scopeIds];
    const localEntries = [...entries];
    const pendingEntry: Entry = { id: now, question: text, loading: false };
    const liveEligible = Boolean(params?.id) && allScopeIdsEligible && (allScopeIdsFormal || allSelected);
    setConversations((current) => {
      if (current.some((conversation) => conversation.id === localConversationId)) {
        return current.map((conversation) => conversation.id === localConversationId ? { ...conversation, entries: [...conversation.entries, { ...pendingEntry, loading: liveEligible }], updatedAt: now } : conversation);
      }
      return [{ id: localConversationId, scopeIds: localScopeIds, entries: [{ ...pendingEntry, loading: liveEligible }], judgments: {}, createdAt: now, updatedAt: now }, ...current];
    });
    setActiveConversationId(localConversationId);
    setQuestion("");
    if (!liveEligible) {
      setConversations((current) => current.map((conversation) => conversation.id === localConversationId ? {
        ...conversation,
        entries: conversation.entries.map((entry) => entry.id === now ? { ...entry, loading: false, error: t("projectChatLiveScopeRequired") } : entry),
        updatedAt: Date.now()
      } : conversation));
      return;
    }
    try {
      const result = await queryProjectChat(apiFetch, params.id!, { question: text, scope_mode: "published", document_version_ids: allScopeIdsFormal ? localScopeIds : undefined, conversation_id: activeConversation?.persisted && isUuid(localConversationId) ? localConversationId : undefined, conversation_title: localEntries[0]?.question || text });
      setConversations((current) => current.map((conversation) => conversation.id === localConversationId ? { ...conversation, id: result.conversation_id || conversation.id, persisted: Boolean(result.conversation_id) || conversation.persisted, entries: conversation.entries.map((entry) => entry.id === now ? { ...entry, recordId: result.chat_record_id ?? undefined, answer: result.answer, citations: result.citations, status: result.status, retrievalStrategy: result.retrieval_strategy, loading: false } : entry), updatedAt: Date.now() } : conversation));
      setHistoryStatus("ready");
      setHistoryError("");
      if (result.conversation_id) setActiveConversationId(result.conversation_id);
    } catch (error) {
      setConversations((current) => current.map((conversation) => conversation.id === localConversationId ? { ...conversation, entries: conversation.entries.map((entry) => entry.id === now ? { ...entry, loading: false, error: retrievalErrorMessage(error, t, format) } : entry), updatedAt: Date.now() } : conversation));
    }
  }

  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function openUploadModal() {
    setUploadFileName("");
    setUploadQuestions([]);
    setUploadError("");
    setUploadDragging(false);
    setBatchCompletedCount(null);
    setActiveValidationRun(null);
    setUploadOpen(true);
  }

  async function processUploadFile(file?: File) {
    setUploadQuestions([]);
    setUploadError("");
    setBatchCompletedCount(null);
    if (!file) return;
    setUploadFileName(file.name);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setUploadError(t("projectChatCsvOnly"));
      return;
    }
    try {
      const rows = parseCsv(await file.text(), t);
      const headers = rows[0]?.map((value, index) => (index ? value : value.replace(/^\uFEFF/, "")).trim()) ?? [];
      const questionIndex = headers.indexOf("question");
      if (questionIndex < 0) throw new Error(t("projectChatCsvMissingQuestion"));
      const expectedAnswerIndex = headers.indexOf("expected_answer");
      const expectedKeywordsIndex = headers.indexOf("expected_keywords");
      const selectedDocumentsIndex = headers.indexOf("selected_document_ids");
      const categoryIndex = headers.indexOf("category");
      const priorityIndex = headers.indexOf("priority");
      const splitList = (value: string | undefined) => (value ?? "").split(/[;,|]/).map((id) => id.trim()).filter(Boolean);
      const valueAt = (row: string[], index: number) => index >= 0 ? (row[index] ?? "").trim() : "";
      const questions = rows.slice(1).map((row): CsvValidationQuestion | null => {
        const questionText = valueAt(row, questionIndex);
        if (!questionText) return null;
        return {
          question: questionText,
          expected_answer: valueAt(row, expectedAnswerIndex) || null,
          expected_keywords: splitList(valueAt(row, expectedKeywordsIndex)),
          selected_document_ids: splitList(valueAt(row, selectedDocumentsIndex)),
          category: valueAt(row, categoryIndex) || null,
          priority: valueAt(row, priorityIndex) || null
        };
      }).filter((item): item is CsvValidationQuestion => item !== null);
      const invalidIds = questions.flatMap((question) => question.selected_document_ids ?? []).filter((id) => !scopeIds.includes(id));
      if (invalidIds.length) throw new Error(format("projectChatCsvInvalidScope", { ids: [...new Set(invalidIds)].join(", ") }));
      if (!questions.length) throw new Error(t("projectChatCsvNoQuestions"));
      setUploadQuestions(questions);
    } catch (error) {
      setUploadError(error instanceof Error && !(`status` in error) ? localizeKnown(error.message) ?? t("projectChatCsvParseFailed") : operationalErrorMessage(error, t, format, "projectChatCsvParseFailed"));
    }
  }

  async function selectUploadFile(event: ChangeEvent<HTMLInputElement>) {
    await processUploadFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function dropUploadFile(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setUploadDragging(false);
    void processUploadFile(event.dataTransfer.files?.[0]);
  }

  function downloadQuestionTemplate() {
    const template = "\uFEFFquestion,expected_answer,expected_keywords,selected_document_ids,category,priority\n"
      + `"${t("projectChatTemplateQuestion")}","${t("projectChatTemplateExpectedAnswer")}","${t("projectChatTemplateKeywords")}","${scopeIds.join(";")}","Model Risk","High"\n`;
    downloadCsv(template, "nomosmart-project-chat-test-template.csv");
  }

  async function confirmBatchUpload() {
    if (!uploadQuestions.length || uploadError || queryBusy) return;
    const started = Date.now();
    const localConversationId = activeConversation?.id ?? newConversationId();
    const localScopeIds = [...scopeIds];
    if (params?.id && localScopeIds.length && allScopeIdsFormal && allScopeIdsEligible) {
      try {
        const run = await createProjectChatValidationRun(apiFetch, params.id, { uploaded_file_name: uploadFileName || null, scope_mode: "published", selected_document_version_ids: localScopeIds, questions: uploadQuestions });
        setActiveValidationRun(run);
        const validationEntries: Entry[] = run.items.map((item, index) => ({ id: started + index, validationItemId: item.id, question: item.question, answer: validationItemMessage(item.status, item.answer, t), citations: item.citations, loading: ["pending", "running"].includes(item.status), error: item.status === "error" ? operationalCodeMessage(item.error_code, t, format, "projectChatRetrievalFailed") : undefined, status: item.answer ? "answered" as const : undefined }));
        setConversations((current) => {
          if (current.some((conversation) => conversation.id === localConversationId)) {
            return current.map((conversation) => conversation.id === localConversationId ? { ...conversation, entries: [...conversation.entries, ...validationEntries], updatedAt: started } : conversation);
          }
          return [{ id: localConversationId, scopeIds: localScopeIds, entries: validationEntries, judgments: {}, createdAt: started, updatedAt: started }, ...current];
        });
        setActiveConversationId(localConversationId);
        setHistoryStatus("ready");
        setHistoryError("");
        setBatchCompletedCount(run.completed_count + run.failed_count);
        return;
      } catch (error) {
        setUploadError(retrievalErrorMessage(error, t, format));
        return;
      }
    }
    setUploadError(t("projectChatBatchLiveScopeRequired"));
  }

  async function retryFailedValidationItems() {
    if (!params?.id || !activeValidationRun) return;
    try {
      const run = await retryFailedProjectChatValidationItems(apiFetch, params.id, activeValidationRun.id);
      setActiveValidationRun(run);
      setBatchCompletedCount(run.completed_count + run.failed_count);
      updateActiveConversation((conversation) => ({ ...conversation, entries: conversation.entries.map((entry) => entry.validationItemId && run.items.some((item) => item.id === entry.validationItemId && ["pending", "running"].includes(item.status)) ? { ...entry, answer: t("projectChatRetryQueued"), loading: true, error: undefined } : entry), updatedAt: Date.now() }));
    } catch (error) {
      setUploadError(retrievalErrorMessage(error, t, format));
    }
  }

  async function persistFeedback(entry: Entry, evaluation: Judgment) {
    const next = evaluation === "revision" ? "needs_revision" : "correct";
    if (!params?.id || !entry.recordId) return;
    await updateProjectChatFeedback(apiFetch, params.id, entry.recordId, { evaluation: next, revision_suggestion: next === "needs_revision" ? revisionText : null });
  }

  async function downloadConversation() {
    if (!params?.id || !activeConversation?.persisted || !isUuid(activeConversation.id)) return;
    try {
      const blob = await downloadProjectChatConversationCsv(apiFetch, params.id, activeConversation.id, { scope_mode: "published" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `nomosmart-project-chat-${activeConversation.id}.csv`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setHistoryError(retrievalErrorMessage(error, t, format));
    }
  }

  return (
    <>
    <section className="project-chat-shell">
      <aside className="project-chat-sidebar">
        <div className="project-document-region">
          <div className="project-chat-scope-head">
            <div><strong>{t("projectChatDocumentSelection")}</strong><small>{format("projectChatActiveDocumentCount", { source: documentSourceLabel, selected: selectedIds.length, total: eligibleIds.length })}</small></div>
            <div><button onClick={() => setSelectedIds(allIds)} type="button">{t("projectChatSelectAll")}</button><button onClick={() => setSelectedIds([])} type="button">{t("projectChatClearSelection")}</button></div>
          </div>
          <label className="project-document-search"><Search size={15} /><input aria-label={t("projectChatSearchReferenceDocuments")} onChange={(event) => setQuery(event.target.value)} placeholder={t("projectChatSearchDocumentPlaceholder")} value={query} /></label>
          <div className="project-document-options">
            {filtered.map((document) => {
              const selected = selectedIds.includes(document.id);
              const eligible = isDocumentEligible(document);
              return <button aria-disabled={!eligible} aria-pressed={selected} className={`${selected ? "selected" : ""}${!eligible ? " disabled" : ""}`} disabled={!eligible} key={document.id} onClick={() => toggleDocument(document.id)} type="button"><span className="document-check">{selected ? <Check size={14} /> : null}</span><span><strong>{document.title}{!eligible ? <em>{documentDisabledLabel(document)}</em> : null}</strong><small>{document.version} · {document.source} · {format("projectChatChunkCountInline", { count: document.chunks })}{!eligible ? ` · ${t("projectChatDocumentUnavailableHelp")}` : ""}</small></span></button>;
            })}
          </div>
          {!selectedIds.length ? <p className="scope-warning">{t("projectChatSelectAtLeastOne")}</p> : null}
          {scopeDirty && selectedIds.length ? <button className="action-button scope-apply" onClick={startScopedConversation} type="button"><MessageSquarePlus size={16} /> {t("projectChatNewConversationWithScope")}</button> : null}
        </div>
        <section className={`project-serving-status readiness-${servingStatus?.readiness ?? "loading"}`} aria-label={t("projectChatServingStatus")}>
          <button aria-expanded={servingExpanded} className="project-serving-toggle" onClick={() => setServingExpanded((current) => !current)} type="button">
            <span><strong>{servingReadinessLabel}</strong><small>{format("projectChatServingSummary", { active: servingStatus?.active_document_count ?? 0, index: servingStatus?.ready_index_count ?? 0, graph: servingStatus?.graph_ready_count ?? 0 })}</small></span>
            {servingExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
          {servingExpanded ? (
            <div className="project-serving-documents">
              {(servingStatus?.documents ?? []).slice(0, 3).map((document) => (
                <span key={document.document_version_id}>{document.document_title} · {document.version_label} · {format("projectChatPublicationGeneration", { generation: document.publication_generation })} · {document.index_ready ? t("projectChatIndexReady") : t("projectChatIndexNotReady")} · {document.graph_sync_status ?? t("projectChatGraphUnknown")}</span>
              ))}
              {servingStatus && servingStatus.documents.length > 3 ? <span>{format("projectChatServingMore", { count: servingStatus.documents.length - 3 })}</span> : null}
            </div>
          ) : null}
        </section>
        <div aria-hidden="true" className="project-sidebar-divider" role="separator" />
        <div className="project-conversation-history">
          <div className="project-history-title"><strong>{t("conversationHistory")}</strong><small>{format("projectChatConversationCount", { count: persistedConversationCount })}</small></div>
          <div className="project-history-list">
            {historyStatus === "loading" ? <div className="project-history-state"><Bot size={16} /><span>{t("projectChatHistoryLoading")}</span></div> : null}
            {historyStatus === "error" ? <div className="project-history-state error"><Bot size={16} /><span><strong>{t("projectChatHistoryLoadFailed")}</strong><small>{localize(historyError)}</small></span></div> : null}
            {historyStatus === "ready" && !orderedConversations.length ? <div className="project-history-state"><MessageSquarePlus size={16} /><span><strong>{t("projectChatHistoryEmptyTitle")}</strong><small>{t("projectChatHistoryEmptyHelp")}</small></span></div> : null}
            {historyStatus !== "loading" && orderedConversations.map((conversation) => {
              const title = conversation.entries[0]?.question || t("newConversation");
              const draft = !conversation.persisted;
              return (
                <div className={`project-history-row${conversation.id === activeConversationId ? " active" : ""}${draft ? " draft" : ""}`} key={conversation.id}>
                  <button className="project-history-select" onClick={() => activateConversation(conversation)} type="button">
                    <MessageSquarePlus size={15} />
                    <span><strong>{title.length > 22 ? `${title.slice(0, 22)}…` : title}{draft ? <em>{t("projectChatDraftBadge")}</em> : null}</strong><small>{draft ? format("projectChatDraftSummary", { documents: conversation.scopeIds.length, time: new Date(conversation.updatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) }) : format(conversation.entries.filter((entry) => entry.recordId && !entry.loading && !entry.error).length === 1 ? "projectChatHistorySummaryOne" : "projectChatHistorySummaryMany", { documents: conversation.scopeIds.length, count: conversation.entries.filter((entry) => entry.recordId && !entry.loading && !entry.error).length, time: new Date(conversation.updatedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) })}</small></span>
                  </button>
                  <button aria-label={format("projectChatDeleteConversationAria", { title })} className="project-history-delete" onClick={() => { setDeleteTargetId(conversation.id); setDeleteError(""); }} type="button"><Trash2 size={14} /></button>
                </div>
              );
            })}
          </div>
        </div>
        <dl className="project-chat-models"><div><dt>LLM</dt><dd>{t("projectChatModelConfigured")}</dd></div><div><dt>Embedding</dt><dd>{t("projectChatModelConfigured")}</dd></div><div><dt>{t("labelIndex")}</dt><dd>{t("projectChatProductionActiveOnly")}</dd></div></dl>
      </aside>

      <div className="chat-conversation-panel project-chat-main">
        <header className="chat-conversation-header">
          <div><strong>{t("projectChatKnowledgeValidation")}</strong><small>{format("projectChatCurrentScopeSummary", { count: scopeIds.length })}</small></div>
          <div className="chat-conversation-header-actions">
            <button className="action-button secondary" disabled={!selectedIds.length || scopeDirty || queryBusy} onClick={openUploadModal} type="button"><Upload size={16} /> {t("uploadTestConversations")}</button>
            <button className="action-button secondary" disabled={!entries.length || !activeConversation?.persisted} onClick={() => void downloadConversation()} type="button"><Download size={16} /> {t("downloadConversation")}</button>
            <button className="action-button secondary" disabled={!selectedIds.length || queryBusy} onClick={startScopedConversation} type="button"><MessageSquarePlus size={16} /> {t("newConversation")}</button>
          </div>
        </header>
        <div className="chat-thread" aria-live="polite" ref={chatThreadRef}>
          {!entries.length ? <div className="chat-empty-state"><Bot size={24} /><strong>{t("projectChatEmptyTitle")}</strong><span>{t("projectChatEmptyHelp")}</span></div> : null}
          {entries.map((entry) => (
            <div className="chat-response-pair" key={entry.id}>
              <article className="chat-message user-message"><div className="message-avatar"><UserRound size={17} /></div><div className="user-message-body"><small>{t("submitReviewCurrentUser")}</small><p>{entry.question}</p></div></article>
              <article aria-busy={entry.loading || undefined} className="chat-message assistant-message">
                <div className="message-avatar"><Bot size={17} /></div>
                <div className="assistant-message-body">
                  <small>NomoSmart · {retrievalLabel(entry.retrievalStrategy)}</small>
                  {entry.loading ? <ChatWaitingIndicator label={t("projectChatQueryingPublishedKnowledge")} /> : entry.error ? <p className="field-error">{localize(entry.error)}</p> : (
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
                    <button className={judgments[entry.id] === "correct" ? "selected correct" : ""} onClick={() => { const now = Date.now(); updateActiveConversation((conversation) => ({ ...conversation, judgments: { ...conversation.judgments, [entry.id]: "correct" }, updatedAt: now })); void persistFeedback(entry, "correct"); }} type="button"><CheckCircle2 size={15} /> {t("answerCorrect")}</button>
                    <button className={judgments[entry.id] === "revision" ? "selected needs-revision" : ""} onClick={() => { setRevisionEntryId(entry.id); setRevisionText(""); }} type="button"><Wrench size={15} /> {t("answerNeedsRevision")}</button>
                  </div>
                </div>
              </article>
            </div>
          ))}
        </div>
        <form aria-busy={queryBusy} className="chat-composer" onSubmit={submit}><label htmlFor="project-chat-question">{t("askQuestion")}</label><div><textarea id="project-chat-question" onChange={(event) => setQuestion(event.target.value)} onKeyDown={submitOnEnter} placeholder={t("projectChatQuestionPlaceholder")} rows={2} value={question} /><button aria-label={queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")} className="action-button" disabled={!question.trim() || !scopeIds.length || scopeDirty || queryBusy} type="submit"><Send size={16} /> {queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")}</button></div>{scopeDirty ? <small className="composer-warning">{t("projectChatScopeChangedWarning")}</small> : null}</form>
      </div>
    </section>
    {uploadOpen ? (
      <div className="modal-backdrop" role="presentation">
        <section aria-labelledby="project-batch-upload-title" aria-modal="true" className="modal-panel chat-small-modal batch-chat-modal" role="dialog">
          <div className="modal-header">
            <div><p className="eyebrow">{t("batchValidation")}</p><h2 id="project-batch-upload-title">{t("uploadTestConversations")}</h2></div>
            <button aria-label={t("close")} className="icon-button" onClick={() => setUploadOpen(false)} type="button"><X size={18} /></button>
          </div>

          {activeValidationRun ? <div className="batch-file-status"><Wrench size={17} /><span><strong>{format("documentChatValidationRun", { id: activeValidationRun.status })}</strong><small>{format("projectChatValidationRunProgress", { completed: activeValidationRun.completed_count + activeValidationRun.failed_count, total: activeValidationRun.total_count })}</small></span></div> : null}
          {validationFinished ? (
            <div className="batch-upload-complete"><CheckCircle2 size={24} /><div><strong>{t("batchCompleted")}</strong><span>{format("projectChatBatchCompletedHelp", { count: batchCompletedCount ?? uploadQuestions.length })}</span></div></div>
          ) : (
            <div className="batch-upload-body">
              <div className="batch-template-row">
                <div><strong>{t("csvTemplate")}</strong><small>question, expected_answer, expected_keywords, selected_document_ids, category, priority</small></div>
                <button className="action-button secondary" onClick={downloadQuestionTemplate} type="button"><FileDown size={16} /> {t("downloadTemplate")}</button>
              </div>
              <label
                className={`csv-upload-field${uploadDragging ? " is-dragging" : ""}`}
                onDragEnter={(event) => { event.preventDefault(); setUploadDragging(true); }}
                onDragLeave={(event) => { event.preventDefault(); setUploadDragging(false); }}
                onDragOver={(event) => event.preventDefault()}
                onDrop={dropUploadFile}
              >
                <Upload size={24} />
                <span><strong>{t("selectCsvFile")}</strong><small>{t("projectChatCsvUploadHelp")}</small></span>
                <input accept=".csv,text/csv" onChange={selectUploadFile} type="file" />
              </label>
              {uploadFileName ? <div className="batch-file-status"><FileText size={17} /><span><strong>{uploadFileName}</strong><small>{uploadError ? localize(uploadError) : format("projectChatValidQuestionCount", { questions: uploadQuestions.length, documents: scopeIds.length })}</small></span></div> : null}
              {uploadError ? <div className="batch-upload-error">{localize(uploadError)}</div> : null}
              {uploadQuestions.length ? <ol className="batch-question-preview">{uploadQuestions.slice(0, 3).map((value, index) => <li key={`${value.question}-${index}`}>{value.question}</li>)}{uploadQuestions.length > 3 ? <li>{format("projectChatMoreQuestions", { count: uploadQuestions.length - 3 })}</li> : null}</ol> : null}
            </div>
          )}
          <div className="modal-actions">
            <button className="action-button secondary" onClick={() => setUploadOpen(false)} type="button">{validationFinished ? t("close") : t("cancel")}</button>
            {canRetryFailedValidation ? <button className="action-button secondary" onClick={() => { void retryFailedValidationItems(); }} type="button">{t("projectChatRetryFailedQuestions")}</button> : null}
            {!activeValidationRun && !validationFinished ? <button className="action-button" disabled={!uploadQuestions.length || Boolean(uploadError)} onClick={confirmBatchUpload} type="button">{t("confirmUpload")}</button> : null}
          </div>
        </section>
      </div>
    ) : null}
    {revisionEntryId !== null ? <div className="modal-backdrop" role="presentation"><section aria-modal="true" className="modal-panel chat-small-modal" role="dialog"><div className="modal-header"><div><p className="eyebrow">{t("answerNeedsRevision")}</p><h2>{t("revisionSuggestion")}</h2></div><button className="icon-button" onClick={() => setRevisionEntryId(null)} type="button"><X size={18} /></button></div><form className="revision-suggestion-form" onSubmit={(event) => { event.preventDefault(); if (!revisionText.trim()) return; const target = entries.find((entry) => entry.id === revisionEntryId); const now = Date.now(); updateActiveConversation((conversation) => ({ ...conversation, judgments: { ...conversation.judgments, [revisionEntryId]: "revision" }, updatedAt: now })); if (target) void persistFeedback(target, "revision"); setRevisionEntryId(null); }}><textarea onChange={(event) => setRevisionText(event.target.value)} placeholder={t("revisionPlaceholder")} required value={revisionText} /><div className="modal-actions"><button className="action-button secondary" onClick={() => setRevisionEntryId(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={!revisionText.trim()} type="submit">{t("saveSuggestion")}</button></div></form></section></div> : null}
    {deleteTargetId ? <div className="modal-backdrop" role="presentation"><section aria-labelledby="project-chat-delete-title" aria-modal="true" className="modal-panel chat-small-modal" role="dialog"><div className="modal-header"><div><p className="eyebrow">{t("projectChatDeleteConversationEyebrow")}</p><h2 id="project-chat-delete-title">{t("projectChatDeleteConversationTitle")}</h2></div><button aria-label={t("close")} className="icon-button" disabled={deleteBusy} onClick={() => setDeleteTargetId(null)} type="button"><X size={18} /></button></div><div className="delete-confirmation-body"><Trash2 size={22} /><p>{t("projectChatDeleteConversationHelp")}</p>{deleteError ? <p className="field-error">{localize(deleteError)}</p> : null}</div><div className="modal-actions"><button className="action-button secondary" disabled={deleteBusy} onClick={() => setDeleteTargetId(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={deleteBusy} onClick={() => { void confirmDeleteConversation(); }} type="button"><Trash2 size={16} /> {deleteBusy ? t("projectChatDeletingConversation") : t("projectChatConfirmDeleteConversation")}</button></div></section></div> : null}
    </>
  );
}
