"use client";

import { useCallback, useRef, useState, type MutableRefObject } from "react";
import { DataTable } from "@/components/DataTable";
import { Bot, Check, Globe2, Info, Layers3, MessageSquareText, Plus, Save, ShieldCheck, X } from "lucide-react";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { activateSystemPrompt, addSystemPromptVersion, createSystemPrompt, deactivateSystemPrompt, listSystemPrompts, type ApiError, type ApiFetch } from "@/lib/api";
import { SettingsCard } from "../SettingsCard";
import { EmptyInlineState, SectionHeader, StateBadge } from "./SystemUi";
import type { FeedbackTone } from "@/lib/feedback";
import type { TranslationKey } from "@/lib/i18nClient";
import type { useOperationGuard } from "../useOperationGuard";
import type { ModelRow, PromptRow, SystemReadState } from "./modalState";
import type { WorkspaceViewDeps } from "./viewDeps";

type OperationGuard = ReturnType<typeof useOperationGuard>;

/** Workspace dependencies shared with the prompt section. */
export type PromptDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  format: (key: TranslationKey, params: Record<string, string | number>) => string;
  localize: (message: string) => string;
  errorMessage: (error: ApiError | Error | null) => string;
  canEditModels: boolean;
  liveModels: ModelRow[];
  promptGuard: OperationGuard["guard"];
  promptOperation: OperationGuard["state"];
  promptBlocked: boolean;
  reloadSystemSection: (section: string, current?: () => boolean) => Promise<boolean>;
  setReadState: (section: string, state: SystemReadState) => void;
  systemReadScope: string;
  systemReadVersions: MutableRefObject<Record<string, number>>;
};

export type PromptState = ReturnType<typeof usePromptState>;

/** System prompt management state (split from SystemManagementWorkspace, OPT424-038). */
export function usePromptState() {
  const [systemPrompts, setSystemPrompts] = useState<PromptRow[]>([]);
  const [selectedPromptId, setSelectedPromptId] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [promptDraftSourceVersion, setPromptDraftSourceVersion] = useState<number | null>(null);
  const [promptModelDraft, setPromptModelDraft] = useState("");
  const [promptNotice, setPromptNotice] = useState<{ message: string; tone: FeedbackTone } | null>(null);
  const promptMessage = promptNotice?.message ?? "";
  const setPromptMessage = useCallback((message: string, tone: FeedbackTone = "info") => setPromptNotice(message ? { message, tone } : null), []);
  const [promptError, setPromptError] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);
  const [promptEditorPrompt, setPromptEditorPrompt] = useState<PromptRow | null>(null);
  const [promptBaseline, setPromptBaseline] = useState("");
  const [promptLeave, setPromptLeave] = useState<(() => void) | null>(null);
  const promptDialogRef = useRef<HTMLElement>(null);
  const promptFocusRef = useRef<HTMLElement | null>(null);
  const promptReceipt = useRef<PromptRow | null>(null);
  const promptMutationScope = useRef<string | null>(null);
  const promptIntent = useRef<{ kind: "save" | "active" | "create"; id?: string; active?: boolean; content?: string } | null>(null);
  return { systemPrompts, setSystemPrompts, selectedPromptId, setSelectedPromptId, promptDraft, setPromptDraft, promptDraftSourceVersion, setPromptDraftSourceVersion, promptModelDraft, setPromptModelDraft, promptNotice, setPromptNotice, promptError, setPromptError, promptSaving, setPromptSaving, promptEditorOpen, setPromptEditorOpen, promptEditorPrompt, setPromptEditorPrompt, promptBaseline, setPromptBaseline, promptLeave, setPromptLeave, promptMessage, setPromptMessage, promptDialogRef, promptFocusRef, promptReceipt, promptMutationScope, promptIntent };
}

/** System prompt management actions, created each render once workspace dependencies exist. */
export function createPromptActions(state: PromptState, deps: PromptDeps) {
  const { systemPrompts, setSystemPrompts, selectedPromptId, setSelectedPromptId, promptDraft, setPromptDraft, promptDraftSourceVersion, setPromptDraftSourceVersion, promptModelDraft, setPromptModelDraft, promptNotice, setPromptNotice, promptError, setPromptError, promptSaving, setPromptSaving, promptEditorOpen, setPromptEditorOpen, promptEditorPrompt, setPromptEditorPrompt, promptBaseline, setPromptBaseline, promptLeave, setPromptLeave, promptMessage, setPromptMessage, promptDialogRef, promptFocusRef, promptReceipt, promptMutationScope, promptIntent } = state;

  async function refreshPrompts(current: () => boolean = () => true) {
    const { reloadSystemSection } = deps;
    const success = await reloadSystemSection("prompts", current);
    if (current() && !success) throw new Error("System read could not be confirmed");
  }

  function requestPromptLeave(action: () => void) {
    const { promptOperation } = deps;
    if (promptSaving || promptOperation.checking) return;
    if (promptEditorOpen && promptDraft !== promptBaseline) {
      promptFocusRef.current = document.activeElement as HTMLElement | null;
      setPromptLeave(() => action);
    } else action();
  }

  async function runPromptMutation(write: () => Promise<PromptRow>, intent: NonNullable<typeof promptIntent.current>, title: TranslationKey) {
    const { errorMessage, promptGuard, t } = deps;
    const token = promptGuard.begin(); if (token === null) return;
    promptIntent.current = intent; promptReceipt.current = null;
    promptMutationScope.current = promptGuard.scope;
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await write();
      if (!promptGuard.current(token)) return;
      promptReceipt.current = prompt; promptGuard.accepted(token);
      // Update the acknowledged baseline now; refreshing the list is a separate read.
      setPromptEditorPrompt(prompt); setPromptBaseline(prompt.content);
      if (intent.kind !== "active") setPromptDraft(prompt.content);
      await refreshPrompts(() => promptGuard.current(token));
      if (!promptGuard.current(token)) return;
      promptGuard.complete(token); setPromptSaving(false); setSelectedPromptId(prompt.id);
      setPromptDraftSourceVersion(null); setPromptEditorOpen(true); setPromptMessage(t(title), "success");
    } catch (caught) {
      if (!promptGuard.current(token)) return;
      promptGuard.failed(token, caught);
      setPromptError(promptGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : errorMessage(caught as ApiError | Error));
    } finally { if (promptGuard.current(token)) setPromptSaving(false); }
  }

  async function queryPromptOutcome() {
    const { apiFetch, promptGuard, setReadState, systemReadScope, systemReadVersions, t } = deps;
    const token = promptGuard.beginCheck(); if (token === null) return;
    try {
      const rows = await listSystemPrompts(apiFetch);
      if (!promptGuard.current(token)) return;
      setSystemPrompts(rows);
      systemReadVersions.current.prompts = (systemReadVersions.current.prompts ?? 0) + 1;
      setReadState("prompts", { scope: systemReadScope, phase: "ready", received: true });
      const sameMutation = promptMutationScope.current === promptGuard.scope;
      const candidateIntent = sameMutation ? promptIntent.current : null;
      const candidateReceipt = sameMutation ? promptReceipt.current : null;
      const targetId = candidateIntent?.kind === "create" ? candidateReceipt?.id : selectedPromptId ?? candidateReceipt?.id ?? candidateIntent?.id;
      const intent = candidateIntent?.kind === "create" || candidateIntent?.id === targetId ? candidateIntent : null;
      const receipt = candidateReceipt?.id === targetId ? candidateReceipt : null;
      const current = rows.find(row => row.id === targetId);
      const confirmed = Boolean(current && (receipt || (intent?.kind === "save" && current.content === intent.content) || (intent?.kind === "active" && current.is_active === intent.active)));
      promptGuard.checked(token, confirmed);
      if (confirmed && current) {
        if (intent?.kind === "create") { setSelectedPromptId(current.id); setPromptEditorOpen(true); }
        if (intent?.kind === "create" || intent?.kind === "save") setPromptDraft(current.content);
        if (intent?.kind === "create" || intent?.kind === "save" || promptDraft === current.content) setPromptLeave(null);
        // Confirm only the current state, not who caused an unacknowledged request.
        setPromptEditorPrompt(current); setPromptBaseline(current.content); setPromptError("");
        setPromptMessage(t("feedbackCurrentStateChecked"));
      } else {
        if (current) { setPromptEditorPrompt(current); setPromptBaseline(current.content); }
        setPromptError(t("feedbackSystemOutcomeChecked"));
        setPromptMessage(t("feedbackCurrentStateChecked"));
      }
    } catch {
      if (!promptGuard.current(token)) return;
      promptGuard.checkFailed(token); setPromptError(t("feedbackOutcomeQueryFailed"));
    }
  }

  async function createGlobalPrompt(modelType: "Chat" | "Judge") {
    const { apiFetch } = deps;
    await runPromptMutation(() => createSystemPrompt(apiFetch, { prompt_scope: "global", model_type: modelType, content: "", is_active: false }), { kind: "create" }, "systemPromptCreated");
  }

  async function createModelPrompt() {
    const { apiFetch, liveModels } = deps;
    const model = liveModels.find(item => item.id === promptModelDraft);
    if (!model || (model.type !== "Chat" && model.type !== "Judge")) return;
    const modelType = model.type;
    await runPromptMutation(() => createSystemPrompt(apiFetch, { prompt_scope: "model", model_type: modelType, model_id: model.id, content: "", is_active: false }), { kind: "create" }, "systemPromptCreated");
  }

  async function savePromptVersion() {
    const { apiFetch, t } = deps;
    const selected = systemPrompts.find(prompt => prompt.id === selectedPromptId) ?? promptEditorPrompt;
    if (!selected || promptDraft.length > 8000 || promptDraft === promptBaseline) return;
    if (!promptDraft.trim()) { setPromptError(t("systemPromptBlankContentError")); return; }
    await runPromptMutation(() => addSystemPromptVersion(apiFetch, selected.id, { content: promptDraft, is_active: selected.is_active, change_reason: null }), { kind: "save", id: selected.id, content: promptDraft }, "systemPromptSaved");
  }

  async function togglePromptActive(active: boolean) {
    const { apiFetch, t } = deps;
    const selected = systemPrompts.find(prompt => prompt.id === selectedPromptId) ?? promptEditorPrompt;
    if (!selected) return;
    if (active && !selected.content.trim()) { setPromptError(t("systemPromptBlankContentError")); return; }
    await runPromptMutation(() => active ? activateSystemPrompt(apiFetch, selected.id, selected.current_version_id) : deactivateSystemPrompt(apiFetch, selected.id), { kind: "active", id: selected.id, active }, active ? "systemPromptActivated" : "systemPromptDeactivated");
  }

  function selectPrompt(prompt: PromptRow) {
    const { promptGuard, t } = deps;
    requestPromptLeave(() => {
      setSelectedPromptId(prompt.id); setPromptDraft(prompt.content); setPromptBaseline(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptError(selectedPromptId === prompt.id && promptGuard.snapshot().phase === "unknown" ? t("feedbackResultUnknown") : selectedPromptId === prompt.id && promptGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : ""); setPromptMessage("");
      setPromptEditorPrompt(prompt); setPromptEditorOpen(true);
    });
  }

  function loadPromptVersionDraft(version: PromptRow["versions"][number]) {
    const { format } = deps;
    requestPromptLeave(() => {
      setPromptDraft(version.content); setPromptDraftSourceVersion(version.version_number);
      setPromptMessage(format("systemPromptLoadedVersionDraft", { version: version.version_number }));
    });
  }

  function renderPromptFeedback() {
    const { localize, promptOperation, t } = deps;
    const needsQuery = promptOperation.phase === "unknown" || promptOperation.phase === "read_failed";
    const reason = promptError || (promptOperation.phase === "unknown" ? t("feedbackResultUnknown") : promptOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : "");
    return <>
      {reason ? <FeedbackMessage tone={needsQuery ? "warning" : "error"} actions={needsQuery ? <button type="button" className="action-button secondary" disabled={promptOperation.checking} onClick={() => void queryPromptOutcome()}>{t(promptOperation.phase === "read_failed" ? "feedbackReloadResult" : "feedbackQueryOutcome")}</button> : undefined}>{promptOperation.checking ? t("feedbackCheckingOutcome") : localize(reason)}</FeedbackMessage> : null}
      {promptMessage ? <FeedbackMessage tone={promptNotice?.tone ?? "info"}>{localize(promptMessage)}</FeedbackMessage> : null}
    </>;
  }

  function handlePromptDialogKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") { event.stopPropagation(); if (promptLeave) { setPromptLeave(null); promptFocusRef.current?.focus(); } else requestPromptLeave(() => setPromptEditorOpen(false)); }
    if (event.key === "Tab") {
      const controls = Array.from(promptDialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled),textarea:not(:disabled),a[href]") ?? []).filter(item => item.getClientRects().length && !item.closest("[inert]"));
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }

  function renderPromptEditor(prompt: PromptRow) {
    const { canEditModels, format, liveModels, promptBlocked, t } = deps;
    const model = prompt.model_id ? liveModels.find((item) => item.id === prompt.model_id) : null;
    const promptDraftBlank = promptDraft.trim().length === 0;
    const currentPromptBlank = prompt.content.trim().length === 0;
    return (
      <div className="system-prompt-editor system-crud-form">
        {model ? <div className="system-prompt-target"><Bot size={16} /><span>{t("systemPromptTargetModel")}</span><strong>{model.name}</strong><small>{model.provider}</small></div> : null}
        {promptDraftSourceVersion ? <div className="system-prompt-layer-note"><Info size={17} /><div><strong>{format("systemPromptLoadedVersionDraft", { version: promptDraftSourceVersion })}</strong><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div> : null}
        <div className="identity-form-grid">
          <label className="identity-wide-field"><span>{t("systemPromptContent")}</span><textarea readOnly={promptBlocked} maxLength={8000} onChange={(event) => setPromptDraft(event.target.value)} rows={12} value={promptDraft} /><small>{format("systemPromptLength", { count: promptDraft.length, max: 8000 })}{promptDraftBlank ? ` · ${t("systemPromptBlankContentError")}` : ""}</small></label>
        </div>
        <div className="system-prompt-history-heading"><div><h3>{t("systemPromptVersionHistory")}</h3><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div>
        <DataTable rows={prompt.versions} rowKey={version => version.id} rowClassName={version => promptDraftSourceVersion === version.version_number ? "selected-row" : undefined} columns={[
          { key: "version", header: t("systemVersion"), cell: version => <button className="system-version-load-button" onClick={() => loadPromptVersionDraft(version)} type="button">{format("systemVersionValue", { version: version.version_number })}</button> },
          { key: "length", header: t("systemLength"), cell: version => version.content.length },
          { key: "status", header: t("systemStatusColumn"), cell: version => <StateBadge tone={version.is_active ? "green" : "gray"}>{version.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge> },
          { key: "time", header: t("systemTime"), cell: version => version.created_at.slice(0, 16).replace("T", " ") },
          { key: "action", header: t("systemAction"), cell: version => <button className="icon-text-button" onClick={() => loadPromptVersionDraft(version)} type="button">{t("systemPromptLoadVersionDraft")}</button> },
        ]} />
        <footer><button className="action-button secondary" disabled={!canEditModels || promptSaving || promptBlocked || prompt.is_active || currentPromptBlank} onClick={() => { void togglePromptActive(true); }} type="button"><Check size={16} />{t("systemEnable")}</button><button className="action-button secondary" disabled={!canEditModels || promptSaving || promptBlocked || !prompt.is_active} onClick={() => { void togglePromptActive(false); }} type="button"><X size={16} />{t("systemDisable")}</button><button className="action-button" disabled={!canEditModels || promptSaving || promptBlocked || promptDraftBlank || promptDraft.length > 8000 || promptDraft === promptBaseline} onClick={() => { void savePromptVersion(); }} type="button"><Save size={16} />{t("systemPromptSaveVersion")}</button></footer>
      </div>
    );
  }

  return { refreshPrompts, requestPromptLeave, runPromptMutation, queryPromptOutcome, createGlobalPrompt, createModelPrompt, savePromptVersion, togglePromptActive, selectPrompt, loadPromptVersionDraft, renderPromptFeedback, handlePromptDialogKey, renderPromptEditor };
}

export type PromptActions = ReturnType<typeof createPromptActions>;

/** System prompt view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createPromptView(state: PromptState, actions: PromptActions, deps: Pick<WorkspaceViewDeps, "canCreateModels" | "format" | "globalChatPrompt" | "globalJudgePrompt" | "liveModels" | "modelSpecificPrompts" | "promptBlocked" | "promptModelOptions" | "sectionReady" | "t">) {
  const { systemPrompts, selectedPromptId, promptModelDraft, setPromptModelDraft, promptSaving, promptEditorOpen } = state;
  const { createGlobalPrompt, createModelPrompt, selectPrompt, renderPromptFeedback } = actions;

  function renderPromptPanel() {
    const { canCreateModels, format, globalChatPrompt, globalJudgePrompt, liveModels, modelSpecificPrompts, promptBlocked, promptModelOptions, sectionReady, t } = deps;
    return (
      <SettingsCard panel="prompts">
      <SectionHeader description={t("systemPromptsDescription")} title={t("systemPrompts")} />
      {!promptEditorOpen ? renderPromptFeedback() : null}
    
      <div className="system-prompt-layer-stack"><Layers3 size={17} /><div><strong>{t("systemPromptLayerOrderTitle")}</strong><span>{t("systemPromptLayerOrderHelp")}</span></div></div>
      <section className="system-prompt-area">
        <div className="system-subsection-title"><div><h3><Globe2 size={18} />{t("systemPromptGlobalSection")}</h3><p>{t("systemPromptGlobalSectionHelp")}</p></div></div>
        <div className="system-prompt-global-grid">
          {globalChatPrompt ? <button className={selectedPromptId === globalChatPrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalChatPrompt)} type="button"><span><MessageSquareText size={18} />{t("systemPromptGlobalChatTitle")}</span><strong>{format("systemVersionValue", { version: globalChatPrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalChatPrompt.is_active ? "green" : "gray"}>{globalChatPrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving || promptBlocked || !sectionReady("prompts")} onClick={() => { void createGlobalPrompt("Chat"); }} type="button"><strong>{t("systemPromptGlobalChatTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
          {globalJudgePrompt ? <button className={selectedPromptId === globalJudgePrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalJudgePrompt)} type="button"><span><ShieldCheck size={18} />{t("systemPromptGlobalJudgeTitle")}</span><strong>{format("systemVersionValue", { version: globalJudgePrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalJudgePrompt.is_active ? "green" : "gray"}>{globalJudgePrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving || promptBlocked || !sectionReady("prompts")} onClick={() => { void createGlobalPrompt("Judge"); }} type="button"><strong>{t("systemPromptGlobalJudgeTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
        </div>
      </section>
      <section className="system-prompt-area">
        <div className="system-subsection-title"><div><h3><Bot size={18} />{t("systemPromptModelSection")}</h3><p>{t("systemPromptModelSectionHelp")}</p></div><div className="system-toolbar compact"><DropdownSelect aria-label={t("systemPromptSelectModel")} onChange={(event) => setPromptModelDraft(event.target.value)} value={promptModelDraft}>{promptModelOptions.length ? promptModelOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.type}</option>) : <option value="">{t("systemPromptNoModelsAvailable")}</option>}</DropdownSelect><button className="action-button secondary" disabled={!canCreateModels || !promptModelDraft || promptSaving || !sectionReady("prompts") || !sectionReady("models")} onClick={() => { void createModelPrompt(); }} type="button"><Plus size={16} />{t("systemPromptAddModel")}</button></div></div>
        {modelSpecificPrompts.length ? <DataTable wrapClassName="system-prompt-model-table" rows={modelSpecificPrompts} rowKey={prompt => prompt.id} rowClassName={prompt => selectedPromptId === prompt.id ? "selected-row" : undefined} onRowClick={selectPrompt} columns={[
          { key: "model", header: t("systemModel"), cell: prompt => <><button className="text-link system-prompt-open" type="button" onClick={(event) => { event.stopPropagation(); selectPrompt(prompt); }} aria-label={format("systemPromptOpenForModel", { name: liveModels.find(model => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—" })}><MessageSquareText size={16} aria-hidden="true" /><strong>{liveModels.find((model) => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—"}</strong></button><small>{prompt.content_hash ?? t("systemPromptBlankHash")}</small></> },
          { key: "type", header: t("systemModelType"), cell: prompt => prompt.model_type },
          { key: "version", header: t("systemVersion"), cell: prompt => prompt.current_version_number ?? "—" },
          { key: "status", header: t("systemStatusColumn"), cell: prompt => <StateBadge tone={prompt.is_active ? "green" : "gray"}>{prompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge> },
        ]} /> : sectionReady("prompts") ? <EmptyInlineState>{t("systemPromptNoModelPrompts")}</EmptyInlineState> : null}
      </section>
    </SettingsCard>
    );
  }

  return { renderPromptPanel };
}
