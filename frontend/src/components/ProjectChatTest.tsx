"use client";

import { scrollChatToEnd } from "@/lib/scrollChatToEnd";
import { Modal } from "@/components/Modal";


import { UiValidationError } from "@/lib/transportError";
import { FeedbackMessage, FeedbackField } from "@/components/FeedbackMessage";
import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, Download, MessageSquarePlus, Send, Trash2, Upload, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { createProjectChatValidationRun, deleteProjectChatConversation, downloadProjectChatConversationCsv, getProjectChatConversation, getProjectChatValidationRun, getProjectServingStatus, listProjectChatConversationPage, listProjectDocuments, queryProjectChat, retryFailedProjectChatValidationItems, updateProjectChatFeedback, type ProjectServingStatusResponse, type ValidationRunResponse } from "@/lib/api";
import { ChatRequestEpoch, chatConversationAccess, chatScopeRevoked } from "@/lib/chatConversationAccess";
import { useI18n } from "@/lib/i18nClient";
import { useReadResource } from "@/lib/useReadResource";
import { operationalCodeMessage, operationalErrorMessage } from "@/lib/operationalMessages";

import { conversationFromHistory, downloadCsv, isUuid, newConversationId, parseValidationQuestionsCsv, retrievalErrorMessage, sameScopeIds, validationItemMessage, type ChatDocument, type CsvValidationQuestion, type Entry, type Judgment, type ProjectConversation } from "./projectChat/projectChatModel";
import { ProjectChatBatchUploadDialog } from "./projectChat/ProjectChatBatchUploadDialog";
import { ProjectChatDocumentScope } from "./projectChat/ProjectChatDocumentScope";
import { ProjectChatEntryPair } from "./projectChat/ProjectChatEntryPair";
import { ProjectChatHistoryList } from "./projectChat/ProjectChatHistoryList";
import { ProjectChatServingStatus } from "./projectChat/ProjectChatServingStatus";

export function ProjectChatTest({ fixedVersionId }: { fixedVersionId?: string }) {
  const params = useParams<{ id?: string }>();
  const { apiFetch, authReady, currentUser } = useAuth();
  const { t, format, localize, localizeKnown } = useI18n();
  const [documents, setDocuments] = useState<ChatDocument[]>([]);
  const [documentSource, setDocumentSource] = useState<"loading" | "live" | "empty" | "error">("loading");
  const [servingStatus, setServingStatus] = useState<ProjectServingStatusResponse | null>(null);
  const servingReadyIds = useMemo(() => new Set((servingStatus?.documents ?? []).filter((document) => document.index_ready).map((document) => document.document_version_id)), [servingStatus]);
  const eligibleIds = useMemo(() => documents.filter((document) => document.documentStatus === "active" && document.versionStatus === "active" && servingReadyIds.has(document.id)
    && (fixedVersionId === undefined || document.id === fixedVersionId)).map((document) => document.id), [documents, servingReadyIds, fixedVersionId]);
  const allIds = eligibleIds;
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [conversations, setConversations] = useState<ProjectConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [historyStatus, setHistoryStatus] = useState<"loading" | "ready" | "error">("loading");
  const [historyError, setHistoryError] = useState("");
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const scopeEpoch = useRef(new ChatRequestEpoch());
  const selectionEpoch = useRef(new ChatRequestEpoch());
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
  const [validationConversationId, setValidationConversationId] = useState<string | null>(null);
  const [servingExpanded, setServingExpanded] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const chatThreadRef = useRef<HTMLDivElement>(null);
  const activeConversation = activeConversationId ? conversations.find((conversation) => conversation.id === activeConversationId) ?? null : null;
  const access = chatConversationAccess(activeConversation?.history, currentUser?.user_id);
  const fixedScopeReady = fixedVersionId === undefined || (isUuid(fixedVersionId) && eligibleIds.includes(fixedVersionId)
    && (!activeConversation || sameScopeIds(activeConversation.scopeIds, [fixedVersionId])));
  const canContinue = authReady && historyStatus === "ready" && fixedScopeReady && !activeConversation?.validationRunId && (!activeConversation?.persisted || access.canContinue);
  const otherConversation = Boolean(activeConversation?.persisted && !access.isMine);
  const authorName = (activeConversation?.persisted ? activeConversation.history?.created_by_display_name : currentUser?.display_name)?.trim() || t("chatAuthorNameMissing");
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

  const discardRevokedScope = useCallback((error: unknown) => {
    if (!chatScopeRevoked(error)) return false;
    scopeEpoch.current.invalidate();
    selectionEpoch.current.invalidate();
    setConversations([]);
    setHistoryCursor(null);
    setHistoryBusy(false);
    setActiveConversationId(null);
    setActiveValidationRun(null);
    setValidationConversationId(null);
    setDocuments([]);
    setServingStatus(null);
    setSelectedIds([]);
    setQuestion("");
    setUploadOpen(false);
    setRevisionEntryId(null);
    setHistoryStatus("error");
    setHistoryError(operationalErrorMessage(error, t, format));
    return true;
  }, [format, t]);

  // OPT424-035: the conversation history, the reference documents with serving status, and a running
  // validation run are read resources. Results commit only while the scope epoch captured when the
  // read started is current; they feed the chat state that questions and uploads also update.
  const projectId = params?.id ?? null;
  const historyScope = useRef(0);
  const readHistory = useCallback((signal: AbortSignal) => listProjectChatConversationPage(apiFetch, projectId!, { signal }), [apiFetch, projectId]);
  useReadResource(readHistory, JSON.stringify([projectId, currentUser?.user_id ?? null, fixedVersionId ?? null]), Boolean(authReady && projectId), {
    onStart: () => {
      scopeEpoch.current.invalidate();
      selectionEpoch.current.invalidate();
      setDocuments([]);
      setServingStatus(null);
      setDocumentSource("loading");
      setConversations([]);
      setActiveConversationId(null);
      setActiveValidationRun(null);
      setValidationConversationId(null);
      setSelectedIds([]);
      setHistoryCursor(null);
      setHistoryBusy(false);
      setQuestion("");
      setUploadOpen(false);
      setRevisionEntryId(null);
      setDeleteTargetId(null);
      historyScope.current = scopeEpoch.current.capture();
      setHistoryStatus("loading");
      setHistoryError("");
    },
    onData: (page) => {
      if (!scopeEpoch.current.isCurrent(historyScope.current)) return;
      const history = page.items.filter((item) => fixedVersionId === undefined || sameScopeIds(item.selected_document_version_ids, [fixedVersionId]));
      setHistoryCursor(page.next_cursor);
      setHistoryStatus("ready");
      setHistoryError("");
      if (history.length) {
        const restored = history.map(conversationFromHistory);
        setConversations(restored);
        // A version-pinned entry starts a fresh own conversation, never a shared one.
        setActiveConversationId(fixedVersionId === undefined ? restored[0].id : null);
        setSelectedIds(fixedVersionId === undefined ? restored[0].scopeIds : [fixedVersionId]);
      } else {
        setConversations([]);
        setActiveConversationId(null);
      }
    },
    onError: (error) => {
      if (!scopeEpoch.current.isCurrent(historyScope.current) || discardRevokedScope(error)) return;
      setConversations([]);
      setActiveConversationId(null);
      setHistoryStatus("error");
      setHistoryError(operationalErrorMessage(error, t, format, "projectChatHistoryLoadFailed"));
    },
  });

  const documentsScope = useRef(0);
  const readDocuments = useCallback((signal: AbortSignal) => Promise.all([listProjectDocuments(apiFetch, projectId!, signal), getProjectServingStatus(apiFetch, projectId!, signal)]), [apiFetch, projectId]);
  // The document labels depend on the interface language, so a language change re-reads them as before.
  useReadResource(readDocuments, JSON.stringify([projectId, currentUser?.user_id ?? null, fixedVersionId ?? null, unavailableVersionLabel]), Boolean(authReady && projectId), {
    onStart: () => { documentsScope.current = scopeEpoch.current.capture(); },
    onData: ([items, status]) => {
      if (!scopeEpoch.current.isCurrent(documentsScope.current)) return;
      setServingStatus(status);
      const chatDocuments = items
        .map((item) => {
          const version = fixedVersionId === undefined ? item.latest_version : item.versions?.find((candidate) => candidate.id === fixedVersionId)
            ?? (item.latest_version?.id === fixedVersionId ? item.latest_version : undefined);
          const servingDocument = status.documents.find((document) => document.document_id === item.id
            && (fixedVersionId === undefined || document.document_version_id === fixedVersionId));
          // The serving manifest identifies Active even when latest_version
          // points at an unpublished candidate.
          const versionId = servingDocument?.document_version_id ?? version?.id ?? item.id;
          return {
            id: versionId,
            documentId: item.id,
            title: item.title,
            version: servingDocument?.version_label ?? version?.version_label ?? unavailableVersionLabel,
            source: item.source_type,
            chunks: servingDocument?.chunk_count ?? 0,
            documentStatus: item.status,
            versionStatus: servingDocument ? "active" : version?.status ?? "missing"
          };
        });
      const eligibleDocuments = chatDocuments.filter((document) => document.documentStatus === "active" && document.versionStatus === "active" && status.documents.some((servingDocument) => servingDocument.document_version_id === document.id && servingDocument.index_ready));
      if (chatDocuments.length) {
        setDocuments(chatDocuments);
        setSelectedIds((current) => fixedVersionId !== undefined ? (eligibleDocuments.some((item) => item.id === fixedVersionId) ? [fixedVersionId] : [])
          : current.length ? current.filter((id) => eligibleDocuments.some((item) => item.id === id)) : eligibleDocuments.map((item) => item.id));
        setDocumentSource(eligibleDocuments.length ? "live" : "empty");
      } else {
        setDocuments([]);
        setSelectedIds([]);
        setDocumentSource("empty");
      }
    },
    onError: (error) => {
      if (!scopeEpoch.current.isCurrent(documentsScope.current)) return;
      if (discardRevokedScope(error)) return;
      setServingStatus(null);
      setDocuments([]);
      setSelectedIds([]);
      setDocumentSource("error");
    },
  });

  async function loadMoreHistory() {
    if (!params?.id || !historyCursor || historyBusy) return;
    const scope = scopeEpoch.current.capture();
    setHistoryBusy(true);
    try {
      const page = await listProjectChatConversationPage(apiFetch, params.id, { cursor: historyCursor });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setConversations((current) => {
        const byId = new Map(current.map((item) => [item.id, item]));
        for (const item of page.items) if (!byId.has(item.id) && (fixedVersionId === undefined || sameScopeIds(item.selected_document_version_ids, [fixedVersionId]))) byId.set(item.id, conversationFromHistory(item));
        return [...byId.values()];
      });
      setHistoryCursor(page.next_cursor);
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope)) setHistoryError(operationalErrorMessage(error, t, format));
    } finally {
      if (scopeEpoch.current.isCurrent(scope)) setHistoryBusy(false);
    }
  }

  useEffect(() => {
    if (!chatThreadRef.current || !entries.length) return;
    scrollChatToEnd(chatThreadRef.current);
  }, [
    activeConversationId,
    entries.length,
    latestEntry?.answer,
    latestEntry?.citations?.length,
    latestEntry?.error,
    latestEntry?.loading
  ]);

  const validationScope = useRef(0);
  const validationRunId = activeValidationRun?.id ?? null;
  const readValidationRun = useCallback((signal: AbortSignal) => getProjectChatValidationRun(apiFetch, projectId!, validationRunId!, signal), [apiFetch, projectId, validationRunId]);
  // Polled every 2.5 s while the run is queued or running; a failed read keeps polling as before.
  useReadResource(readValidationRun, validationRunId, Boolean(authReady && projectId && validationRunId && validationRunning), {
    poll: () => 2500,
    onStart: () => { validationScope.current = scopeEpoch.current.capture(); },
    onData: (run) => {
      if (!scopeEpoch.current.isCurrent(validationScope.current)) return;
      setActiveValidationRun(run);
      setBatchCompletedCount(run.completed_count + run.failed_count);
      setConversations((current) => current.map((conversation) => conversation.id === validationConversationId ? {
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
    },
    onError: (error) => {
      if (!scopeEpoch.current.isCurrent(validationScope.current) || discardRevokedScope(error)) return;
      setConversations((current) => current.map((conversation) => conversation.id === validationConversationId ? { ...conversation, entries: conversation.entries.map((entry) => entry.validationItemId ? { ...entry, loading: false, error: retrievalErrorMessage(error, t, format) } : entry), updatedAt: Date.now() } : conversation));
    },
  });

  function toggleDocument(id: string) {
    if (fixedVersionId !== undefined || !eligibleIds.includes(id)) return;
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

  function startScopedConversation() {
    if (!selectedIds.length || historyStatus !== "ready" || !fixedScopeReady) return;
    const existingDraft = conversations.find((conversation) => !conversation.persisted && !conversation.entries.length && sameScopeIds(conversation.scopeIds, selectedIds));
    if (existingDraft) {
      activateConversation(existingDraft);
      return;
    }
    const now = Date.now();
    const conversation: ProjectConversation = { id: newConversationId(), scopeIds: [...selectedIds], entries: [], judgments: {}, createdAt: now, updatedAt: now };
    setConversations((current) => [conversation, ...current]);
    activateConversation(conversation);
  }

  function activateConversation(conversation: ProjectConversation) {
    if (fixedVersionId !== undefined && !sameScopeIds(conversation.scopeIds, [fixedVersionId])) return;
    selectionEpoch.current.invalidate();
    setRevisionEntryId(null);
    setRevisionText("");
    setUploadOpen(false);
    setUploadError("");
    setDeleteTargetId(null);
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
    if (target.persisted && !chatConversationAccess(target.history, currentUser?.user_id).canDelete) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    setDeleteBusy(true);
    setDeleteError("");
    try {
      if (params?.id && isUuid(target.id) && target.persisted) {
        await deleteProjectChatConversation(apiFetch, params.id, target.id);
      }
      if (!scopeEpoch.current.isCurrent(scope)) return;
      const remaining = conversations.filter((conversation) => conversation.id !== target.id);
      setConversations((current) => current.filter((conversation) => conversation.id !== target.id));
      if (selectionEpoch.current.isCurrent(selection) && target.id === activeConversationId) {
        const nextActive = [...remaining].sort((a, b) => b.updatedAt - a.updatedAt)[0];
        if (nextActive) activateConversation(nextActive);
        else {
          selectionEpoch.current.invalidate();
          setActiveConversationId(null);
          setQuestion("");
          if (!selectedIds.length && allIds.length) setSelectedIds(allIds);
        }
      }
      setDeleteTargetId(null);
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope) && selectionEpoch.current.isCurrent(selection)) setDeleteError(operationalErrorMessage(error, t, format, "projectChatDeleteFailed"));
    } finally {
      if (scopeEpoch.current.isCurrent(scope)) setDeleteBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || !scopeIds.length || scopeDirty || queryBusy || !canContinue) return;
    const scope = scopeEpoch.current.capture();
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
      const result = await queryProjectChat(apiFetch, params.id!, { question: text, scope_mode: "published", document_version_ids: fixedVersionId !== undefined ? [fixedVersionId] : allScopeIdsFormal ? localScopeIds : undefined, conversation_id: isUuid(localConversationId) ? localConversationId : undefined, conversation_title: localEntries[0]?.question || text });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setConversations((current) => current.map((conversation) => conversation.id === localConversationId ? { ...conversation, id: result.conversation_id || conversation.id, persisted: Boolean(result.conversation_id) || conversation.persisted, entries: conversation.entries.map((entry) => entry.id === now ? { ...entry, recordId: result.chat_record_id ?? undefined, answer: result.answer, citations: result.citations, status: result.status, retrievalStrategy: result.retrieval_strategy, loading: false } : entry), updatedAt: Date.now() } : conversation));
      setHistoryStatus("ready");
      setHistoryError("");
      if (result.conversation_id) {
        setActiveConversationId((current) => current === localConversationId ? result.conversation_id! : current);
        const saved = await getProjectChatConversation(apiFetch, params.id!, result.conversation_id);
        if (!scopeEpoch.current.isCurrent(scope)) return;
        setConversations((current) => current.map((conversation) => conversation.id === saved.id ? conversationFromHistory(saved) : conversation));
      }
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope)) return;
      if (discardRevokedScope(error)) return;
      setConversations((current) => current.map((conversation) => conversation.id === localConversationId ? { ...conversation, entries: conversation.entries.map((entry) => entry.id === now ? { ...entry, loading: false, error: retrievalErrorMessage(error, t, format) } : entry), updatedAt: Date.now() } : conversation));
    }
  }

  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function openUploadModal() {
    if (!canContinue) return;
    setUploadFileName("");
    setUploadQuestions([]);
    setUploadError("");
    setUploadDragging(false);
    setBatchCompletedCount(null);
    setActiveValidationRun(null);
    setUploadOpen(true);
  }

  async function processUploadFile(file?: File) {
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
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
      const contents = await file.text();
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      const questions = parseValidationQuestionsCsv(contents, scopeIds, format);
      setUploadQuestions(questions);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      setUploadError(error instanceof UiValidationError ? t(error.key) : error instanceof Error && !(`status` in error) ? localizeKnown(error.message) ?? t("projectChatCsvParseFailed") : operationalErrorMessage(error, t, format, "projectChatCsvParseFailed"));
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
    if (!uploadQuestions.length || uploadError || queryBusy || !canContinue) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    const started = Date.now();
    const localConversationId = newConversationId();
    const localScopeIds = [...scopeIds];
    if (params?.id && localScopeIds.length && allScopeIdsFormal && allScopeIdsEligible) {
      try {
        const run = await createProjectChatValidationRun(apiFetch, params.id, { uploaded_file_name: uploadFileName || null, scope_mode: "published", selected_document_version_ids: localScopeIds, questions: uploadQuestions });
        if (!scopeEpoch.current.isCurrent(scope)) return;
        setActiveValidationRun(run);
        setValidationConversationId(localConversationId);
        const validationEntries: Entry[] = run.items.map((item, index) => ({ id: started + index, validationItemId: item.id, question: item.question, answer: validationItemMessage(item.status, item.answer, t), citations: item.citations, loading: ["pending", "running"].includes(item.status), error: item.status === "error" ? operationalCodeMessage(item.error_code, t, format, "projectChatRetrievalFailed") : undefined, status: item.answer ? "answered" as const : undefined }));
        setConversations((current) => {
          if (current.some((conversation) => conversation.id === localConversationId)) {
            return current.map((conversation) => conversation.id === localConversationId ? { ...conversation, entries: [...conversation.entries, ...validationEntries], updatedAt: started } : conversation);
          }
          return [{ id: localConversationId, scopeIds: localScopeIds, entries: validationEntries, judgments: {}, createdAt: started, updatedAt: started, validationRunId: run.id }, ...current];
        });
        if (selectionEpoch.current.isCurrent(selection)) setActiveConversationId(localConversationId);
        setHistoryStatus("ready");
        setHistoryError("");
        setBatchCompletedCount(run.completed_count + run.failed_count);
        return;
      } catch (error) {
        if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
        if (discardRevokedScope(error)) return;
        setUploadError(retrievalErrorMessage(error, t, format));
        return;
      }
    }
    setUploadError(t("projectChatBatchLiveScopeRequired"));
  }

  async function retryFailedValidationItems() {
    if (!params?.id || !activeValidationRun || otherConversation || activeConversationId !== validationConversationId) return;
    const scope = scopeEpoch.current.capture();
    try {
      const run = await retryFailedProjectChatValidationItems(apiFetch, params.id, activeValidationRun.id);
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setActiveValidationRun(run);
      setBatchCompletedCount(run.completed_count + run.failed_count);
      setConversations((current) => current.map((conversation) => conversation.id === validationConversationId ? { ...conversation, entries: conversation.entries.map((entry) => entry.validationItemId && run.items.some((item) => item.id === entry.validationItemId && ["pending", "running"].includes(item.status)) ? { ...entry, answer: t("projectChatRetryQueued"), loading: true, error: undefined } : entry) } : conversation));
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope)) setUploadError(retrievalErrorMessage(error, t, format));
    }
  }

  async function persistFeedback(entry: Entry, evaluation: Judgment) {
    const next = evaluation === "revision" ? "needs_revision" : "correct";
    if (!params?.id || !entry.recordId || !access.canEvaluate || !activeConversationId) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    const conversationId = activeConversationId;
    try {
      const updated = await updateProjectChatFeedback(apiFetch, params.id, entry.recordId, { evaluation: next, revision_suggestion: next === "needs_revision" ? revisionText : null });
      if (!scopeEpoch.current.isCurrent(scope)) return;
      setConversations((current) => current.map((item) => item.id === conversationId ? { ...item,
        judgments: { ...item.judgments, [entry.id]: evaluation },
        history: item.history ? { ...item.history, records: item.history.records.map((record) => record.id === updated.id ? updated : record) } : undefined,
      } : item));
      if (selectionEpoch.current.isCurrent(selection)) setRevisionEntryId(null);
    } catch (error) {
      if (scopeEpoch.current.isCurrent(scope) && discardRevokedScope(error)) return;
      if (scopeEpoch.current.isCurrent(scope) && selectionEpoch.current.isCurrent(selection)) setHistoryError(operationalErrorMessage(error, t, format));
    }
  }

  async function downloadConversation() {
    if (!params?.id || !activeConversation?.persisted || !isUuid(activeConversation.id) || !access.canExport) return;
    const scope = scopeEpoch.current.capture();
    const selection = selectionEpoch.current.capture();
    try {
      const blob = await downloadProjectChatConversationCsv(apiFetch, params.id, activeConversation.id, { scope_mode: "published" });
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection)) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `nomosmart-project-chat-${activeConversation.id}.csv`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      if (!scopeEpoch.current.isCurrent(scope) || !selectionEpoch.current.isCurrent(selection) || discardRevokedScope(error)) return;
      setHistoryError(retrievalErrorMessage(error, t, format));
    }
  }

  return (
    <>
    {fixedVersionId !== undefined ? <p className={fixedScopeReady ? "feature-summary" : "field-error"} role={fixedScopeReady ? "status" : "alert"}>
      {t(fixedScopeReady ? "projectChatFixedScopeHelp" : "projectChatFixedScopeUnavailable")}
    </p> : null}
    <section className="project-chat-shell">
      <aside className="project-chat-sidebar">
        <ProjectChatDocumentScope allIds={allIds} documentDisabledLabel={documentDisabledLabel} documentSourceLabel={documentSourceLabel} eligibleIds={eligibleIds} filtered={filtered} fixedVersionId={fixedVersionId} isDocumentEligible={isDocumentEligible} query={query} scopeDirty={scopeDirty} selectedIds={selectedIds} setQuery={setQuery} setSelectedIds={setSelectedIds} startScopedConversation={startScopedConversation} toggleDocument={toggleDocument} />
        <ProjectChatServingStatus servingExpanded={servingExpanded} servingReadinessLabel={servingReadinessLabel} servingStatus={servingStatus} setServingExpanded={setServingExpanded} />
        <div aria-hidden="true" className="project-sidebar-divider" role="separator" />
        <ProjectChatHistoryList activateConversation={activateConversation} activeConversationId={activeConversationId} currentUser={currentUser} historyBusy={historyBusy} historyCursor={historyCursor} historyError={historyError} historyStatus={historyStatus} loadMoreHistory={loadMoreHistory} orderedConversations={orderedConversations} persistedConversationCount={persistedConversationCount} setDeleteError={setDeleteError} setDeleteTargetId={setDeleteTargetId} />
        <dl className="project-chat-models"><div><dt>LLM</dt><dd>{t("projectChatModelConfigured")}</dd></div><div><dt>Embedding</dt><dd>{t("projectChatModelConfigured")}</dd></div><div><dt>{t("labelIndex")}</dt><dd>{t("projectChatProductionActiveOnly")}</dd></div></dl>
      </aside>

      <div className="chat-conversation-panel project-chat-main">
        <header className="chat-conversation-header">
          <div><strong>{t("projectChatKnowledgeValidation")}</strong><small>{format("projectChatCurrentScopeSummary", { count: scopeIds.length })}</small></div>
          <div className="chat-conversation-header-actions">
            <button className="action-button secondary" disabled={!selectedIds.length || scopeDirty || queryBusy || !canContinue} onClick={openUploadModal} type="button"><Upload size={16} /> {t("uploadTestConversations")}</button>
            <button className="action-button secondary" disabled={!entries.length || !access.canExport} onClick={() => void downloadConversation()} type="button"><Download size={16} /> {t("downloadConversation")}</button>
            <button className="action-button secondary" disabled={!selectedIds.length || historyStatus !== "ready"} onClick={startScopedConversation} type="button"><MessageSquarePlus size={16} /> {t("chatNewOwnConversation")}</button>
          </div>
        </header>
        <div className="chat-thread" aria-live="polite" ref={chatThreadRef}>
          {historyStatus === "ready" && historyError ? <FeedbackField>{localize(historyError)}</FeedbackField> : null}
          {(activeConversation?.persisted || activeConversation?.validationRunId) && !canContinue ? <FeedbackMessage tone="info">{t(otherConversation ? "chatOtherConversationReadOnly" : "chatConversationWriteDenied")}</FeedbackMessage> : null}
          {!entries.length ? <div className="chat-empty-state"><Bot size={24} /><strong>{t("projectChatEmptyTitle")}</strong><span>{t("projectChatEmptyHelp")}</span></div> : null}
          {entries.map((entry) => <ProjectChatEntryPair access={access} authorName={authorName} entry={entry} judgments={judgments} key={entry.id} persistFeedback={persistFeedback} setRevisionEntryId={setRevisionEntryId} setRevisionText={setRevisionText} />)}
        </div>
        <form aria-busy={queryBusy} className="chat-composer" onSubmit={submit}><label htmlFor="project-chat-question">{t("askQuestion")}</label><div><textarea disabled={!canContinue || queryBusy} id="project-chat-question" onChange={(event) => setQuestion(event.target.value)} onKeyDown={submitOnEnter} placeholder={t("projectChatQuestionPlaceholder")} rows={2} value={question} /><button aria-label={queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")} className="action-button" disabled={!canContinue || !question.trim() || !scopeIds.length || scopeDirty || queryBusy} type="submit"><Send size={16} /> {queryBusy ? t("chatWaitingForAnswer") : t("sendQuestion")}</button></div>{scopeDirty ? <FeedbackMessage tone="warning">{t("projectChatScopeChangedWarning")}</FeedbackMessage> : null}</form>
      </div>
    </section>
    {uploadOpen ? <ProjectChatBatchUploadDialog activeValidationRun={activeValidationRun} batchCompletedCount={batchCompletedCount} canRetryFailedValidation={canRetryFailedValidation} confirmBatchUpload={confirmBatchUpload} downloadQuestionTemplate={downloadQuestionTemplate} dropUploadFile={dropUploadFile} retryFailedValidationItems={retryFailedValidationItems} scopeIds={scopeIds} selectUploadFile={selectUploadFile} setUploadDragging={setUploadDragging} setUploadOpen={setUploadOpen} uploadDragging={uploadDragging} uploadError={uploadError} uploadFileName={uploadFileName} uploadQuestions={uploadQuestions} validationFinished={validationFinished} /> : null}
    {revisionEntryId !== null ? <Modal onEscape={() => setRevisionEntryId(null)} aria-labelledby="project-chat-revision-title" className="modal-panel chat-small-modal"><div className="modal-header"><div><p className="eyebrow">{t("answerNeedsRevision")}</p><h2 id="project-chat-revision-title">{t("revisionSuggestion")}</h2></div><button aria-label={t("close")} className="icon-button" onClick={() => setRevisionEntryId(null)} type="button"><X size={18} /></button></div><form className="revision-suggestion-form" onSubmit={(event) => { event.preventDefault(); if (!revisionText.trim() || !access.canEvaluate) return; const target = entries.find((entry) => entry.id === revisionEntryId); if (target) void persistFeedback(target, "revision"); }}><textarea aria-label={t("revisionSuggestion")} onChange={(event) => setRevisionText(event.target.value)} placeholder={t("revisionPlaceholder")} required value={revisionText} /><div className="modal-actions"><button className="action-button secondary" onClick={() => setRevisionEntryId(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={!revisionText.trim()} type="submit">{t("saveSuggestion")}</button></div></form></Modal> : null}
    {deleteTargetId ? <Modal onEscape={() => { if (!deleteBusy) setDeleteTargetId(null); }} aria-labelledby="project-chat-delete-title" className="modal-panel chat-small-modal"><div className="modal-header"><div><p className="eyebrow">{t("projectChatDeleteConversationEyebrow")}</p><h2 id="project-chat-delete-title">{t("projectChatDeleteConversationTitle")}</h2></div><button aria-label={t("close")} className="icon-button" disabled={deleteBusy} onClick={() => setDeleteTargetId(null)} type="button"><X size={18} /></button></div><div className="delete-confirmation-body"><Trash2 size={22} /><p>{t("projectChatDeleteConversationHelp")}</p>{deleteError ? <FeedbackField>{localize(deleteError)}</FeedbackField> : null}</div><div className="modal-actions"><button className="action-button secondary" disabled={deleteBusy} onClick={() => setDeleteTargetId(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={deleteBusy} onClick={() => { void confirmDeleteConversation(); }} type="button"><Trash2 size={16} /> {deleteBusy ? t("projectChatDeletingConversation") : t("projectChatConfirmDeleteConversation")}</button></div></Modal> : null}
    </>
  );
}
