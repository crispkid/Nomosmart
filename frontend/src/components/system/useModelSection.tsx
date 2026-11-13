"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { createModel, deleteModel, setDefaultModel, testModel, updateModel, type AIModelPayload, type ApiError, type ApiFetch } from "@/lib/api";
import { Bot, ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, LockKeyhole, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import { AIModelCredentialClearControl, OpenAiApiModeField } from "@/components/AIModelCompatibilityFields";
import { aiModelProviderName } from "@/components/AIModelInventoryFields";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackForm } from "@/components/FeedbackForm";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { formatDateTime } from "@/lib/dateFormat";
import { UiValidationError } from "@/lib/transportError";
import { SettingsCard } from "../SettingsCard";
import { EmptyInlineState, SectionHeader, StateBadge } from "./SystemUi";
import { aiProviders, containsSecretConfigKey, modelConfigValue, modelRow, nativePdfConfigFromForm, nativePdfLimitFields, nativePdfLimitLabels, nativePdfProfile, normalizedProvider, pairedEmbeddingModelIds, providerHelpKey, providerNeedsCredential, type ModelDeleteDependency } from "./modelHelpers";
import type { FeedbackMessage as FeedbackNotice } from "@/lib/feedback";
import type { TranslationKey } from "@/lib/i18nClient";
import type { ModalState, ModelRow } from "./modalState";
import type { WorkspaceViewDeps } from "./viewDeps";

export type QuickMutationTarget = { kind: "model" | "role"; id: string; field: "is_active" | "is_default"; value: boolean };

/** Workspace dependencies shared with the model section. */
export type ModelDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  modal: ModalState | null;
  notify: (message: FeedbackNotice, toast?: boolean) => void;
  refreshModelTable: () => Promise<void>;
  reloadSystemSection: (section: string, current?: () => boolean) => Promise<boolean>;
  runModalMutation: <T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title?: TranslationKey) => Promise<void>;
  runQuickMutation: (target: QuickMutationTarget, write: () => Promise<unknown>, refresh: (current: () => boolean) => Promise<void>) => Promise<void>;
  setLiveModels: Dispatch<SetStateAction<ModelRow[]>>;
  setModal: (next: SetStateAction<ModalState | null>) => void;
  setModalError: Dispatch<SetStateAction<string>>;
  setSystemError: Dispatch<SetStateAction<ApiError | Error | null>>;
};

export type ModelState = ReturnType<typeof useModelState>;

/** AI model management state (split from SystemManagementWorkspace, OPT424-038). */
export function useModelState() {
  const [modelTableRows, setModelTableRows] = useState<ModelRow[]>([]);
  const [modelTableTotal, setModelTableTotal] = useState(0);
  const [modelTableReceived, setModelTableReceived] = useState(false);
  const [modelTablePage, setModelTablePage] = useState(1);
  const [modelTablePageSize, setModelTablePageSize] = useState(20);
  const [modelTableType, setModelTableType] = useState("all");
  const [modelTableLoading, setModelTableLoading] = useState(false);
  const [modelTableError, setModelTableError] = useState("");
  const [modelDeleteConfirmation, setModelDeleteConfirmation] = useState("");
  const [modelDeleteDependencies, setModelDeleteDependencies] = useState<ModelDeleteDependency[]>([]);
  const [modelProviderDraft, setModelProviderDraft] = useState("OpenAI");
  const [modelTypeDraft, setModelTypeDraft] = useState("Chat");
  const [modelPairDraft, setModelPairDraft] = useState<string[]>([]);
  const [modelCredentialClearDraft, setModelCredentialClearDraft] = useState(false);
  const [modelCredentialClearConfirmation, setModelCredentialClearConfirmation] = useState("");
  return { modelTableRows, setModelTableRows, modelTableTotal, setModelTableTotal, modelTableReceived, setModelTableReceived, modelTablePage, setModelTablePage, modelTablePageSize, setModelTablePageSize, modelTableType, setModelTableType, modelTableLoading, setModelTableLoading, modelTableError, setModelTableError, modelDeleteConfirmation, setModelDeleteConfirmation, modelDeleteDependencies, setModelDeleteDependencies, modelProviderDraft, setModelProviderDraft, modelTypeDraft, setModelTypeDraft, modelPairDraft, setModelPairDraft, modelCredentialClearDraft, setModelCredentialClearDraft, modelCredentialClearConfirmation, setModelCredentialClearConfirmation };
}

/** AI model management actions, created each render once workspace dependencies exist. */
export function createModelActions(state: ModelState, deps: ModelDeps) {
  const { modelTableRows, setModelTableRows, modelTableTotal, setModelTableTotal, modelTableReceived, setModelTableReceived, modelTablePage, setModelTablePage, modelTablePageSize, setModelTablePageSize, modelTableType, setModelTableType, modelTableLoading, setModelTableLoading, modelTableError, setModelTableError, modelDeleteConfirmation, setModelDeleteConfirmation, modelDeleteDependencies, setModelDeleteDependencies, modelProviderDraft, setModelProviderDraft, modelTypeDraft, setModelTypeDraft, modelPairDraft, setModelPairDraft, modelCredentialClearDraft, setModelCredentialClearDraft, modelCredentialClearConfirmation, setModelCredentialClearConfirmation } = state;
  const { t } = deps;

  const modelDeleteDependencyLabel = (type: string) => {
    if (type === "system_default") return t("systemModelDependencyDefault");
    if (type === "current_project_assignment") return t("systemModelDependencyProject");
    if (type === "running_ocr_pipeline") return t("systemModelDependencyPipeline");
    if (type === "active_chat_pairing") return t("systemModelDependencyPairing");
    if (type === "active_system_prompt") return t("systemModelDependencyPrompt");
    return type;
  };

  async function runModelConnectionTest(model: ModelRow) {
    const { apiFetch, notify, setLiveModels, setSystemError } = deps;
    setSystemError(null);
    try {
      const tested = await testModel(apiFetch, model.id);
      setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(tested) : item));
      setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(tested) : item));
      notify({ id: crypto.randomUUID(), scope: "system", tone: "success", title: "feedbackConnectionVerified" });
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }

  async function refreshModels(current: () => boolean = () => true) {
    const { refreshModelTable, reloadSystemSection } = deps;
    const success = await reloadSystemSection("models", current);
    if (current() && !success) throw new Error("System read could not be confirmed");
    if (current()) await refreshModelTable();
  }

  async function activateModel(model: ModelRow) {
    const { apiFetch, runQuickMutation } = deps;
    await runQuickMutation({ kind: "model", id: model.id, field: "is_active", value: true }, () => updateModel(apiFetch, model.id, { is_active: true }), refreshModels);
  }

  async function deactivateModelRow(model: ModelRow, accepted: () => void) {
    const { apiFetch, setLiveModels } = deps;
    const updated = await updateModel(apiFetch, model.id, { is_active: false }); accepted();
    setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
  }

  function openModelDeleteModal(model: ModelRow) {
    const { setModal, setModalError } = deps;
    setModelDeleteConfirmation("");
    setModelDeleteDependencies([]);
    setModalError("");
    setModal({ type: "model-delete", model });
  }

  async function submitModelDelete(model: ModelRow) {
    const { apiFetch, runModalMutation } = deps;
    if (!model.raw || modelDeleteConfirmation !== model.name) return;
    setModelDeleteDependencies([]);
    await runModalMutation(async () => {
      try { return await deleteModel(apiFetch, model.id, { confirmation_name: modelDeleteConfirmation, config_version: model.raw!.config_version }); }
      catch (caught) {
        const details = (caught as ApiError).details as { dependencies?: ModelDeleteDependency[] } | undefined;
        if ((caught as ApiError).status === 409 && Array.isArray(details?.dependencies)) setModelDeleteDependencies(details.dependencies);
        throw caught;
      }
    }, (_result, current) => refreshModels(current), "systemModelDeleted");
  }

  function openModelModal(model?: ModelRow) {
    const { setModal } = deps;
    setModelProviderDraft(normalizedProvider(model?.provider));
    setModelTypeDraft(model?.type ?? "Chat");
    setModelPairDraft(pairedEmbeddingModelIds(model));
    setModelCredentialClearDraft(false);
    setModelCredentialClearConfirmation("");
    setModal(model ? { type: "model", model } : { type: "model" });
  }

  function toggleModelPair(modelId: string, checked: boolean) {
    setModelPairDraft((current) => checked ? [...new Set([...current, modelId])] : current.filter((id) => id !== modelId));
  }

  async function submitModel(formData: FormData) {
    const { apiFetch, modal, runModalMutation } = deps;
    await runModalMutation(async () => {
      const configText = String(formData.get("config_advanced") || "{}");
      let config: Record<string, unknown> = {};
      try { config = JSON.parse(configText) as Record<string, unknown>; } catch { throw new UiValidationError("systemConfigJsonInvalid"); }
      if (containsSecretConfigKey(config)) throw new UiValidationError("systemConfigJsonNoSecrets");
      const provider = String(formData.get("provider") || "OpenAI");
      const modelType = String(formData.get("model_type") || "Chat");
      if (modelType === "OCR" && provider === "OpenAI") {
        const profile = nativePdfConfigFromForm(formData, modal?.type === "model" ? modal.model : undefined, config.native_pdf);
        if (profile) config.native_pdf = profile;
      }
      const modelName = String(formData.get("model_name") || "").trim();
      const baseUrl = String(formData.get("base_url") || "").trim();
      const endpoint = String(formData.get("endpoint") || baseUrl || "").trim();
      const pairedIds = formData.getAll("paired_embedding_model_ids").map((value) => String(value)).filter(Boolean);
      if (modelType === "Chat" && pairedIds.length === 0) throw new UiValidationError("systemChatModelPairRequired");
      const timeoutSeconds = Number(formData.get("timeout_seconds") || 0);
      if (modelName) config.model_name = modelName;
      if (baseUrl) config.base_url = baseUrl;
      if (String(formData.get("api_version") || "").trim()) config.api_version = String(formData.get("api_version")).trim();
      if (String(formData.get("organization_id") || "").trim()) config.organization_id = String(formData.get("organization_id")).trim();
      if (String(formData.get("project_id") || "").trim()) config.project_id = String(formData.get("project_id")).trim();
      if (String(formData.get("anthropic_version") || "").trim()) config.anthropic_version = String(formData.get("anthropic_version")).trim();
      if (String(formData.get("embedding_dimension") || "").trim()) config.embedding_dimension = Number(formData.get("embedding_dimension"));
      if (timeoutSeconds > 0) config.timeout_seconds = timeoutSeconds;
      if (provider === "vLLM") config.openai_compatible = true;
      if (provider === "OpenAI" && (modelType === "Chat" || modelType === "Judge")) {
        config.api_mode = String(formData.get("api_mode") || "responses");
      } else {
        delete config.api_mode;
      }
      if (modelType === "Chat") config.paired_embedding_model_ids = pairedIds;
      else delete config.paired_embedding_model_ids;
      const pricingKeys = ["input_cost_per_million_tokens", "output_cost_per_million_tokens", "embedding_cost_per_million_tokens"];
      pricingKeys.forEach((key) => delete config[key]);
      let hasPricing = false;
      for (const key of pricingKeys) {
        const value = String(formData.get(key) ?? "").trim();
        if (!value) continue;
        const price = Number(value);
        if (!Number.isFinite(price) || price < 0) throw new UiValidationError("systemModelPricingNonNegative");
        config[key] = value;
        hasPricing = true;
      }
      const costCurrency = String(formData.get("cost_currency") || "").trim().toUpperCase();
      if (hasPricing && !costCurrency) throw new UiValidationError("systemModelPricingCurrencyRequired");
      if (costCurrency) config.cost_currency = costCurrency;
      else delete config.cost_currency;
      if (provider === "Custom") {
        const headersText = String(formData.get("headers_json") || "{}");
        let headers: Record<string, unknown> = {};
        try { headers = JSON.parse(headersText) as Record<string, unknown>; } catch { throw new UiValidationError("systemHeadersJsonInvalid"); }
        if (containsSecretConfigKey(headers)) throw new UiValidationError("systemHeadersJsonNoSecrets");
        config.headers = headers;
      }
      const payload: AIModelPayload = {
        name: String(formData.get("name") || "").trim(),
        model_type: modelType,
        provider,
        endpoint: endpoint || null,
        is_active: formData.get("is_active") === "on",
        is_default: formData.get("is_default") === "on",
        config
      };
      const apiKey = String(formData.get("api_key") || "");
      const secretRef = String(formData.get("api_key_secret_ref") || "").trim();
      if (modal?.type === "model" && modal.model) {
        if (modelCredentialClearDraft) {
          if (modelCredentialClearConfirmation !== modal.model.name) throw new UiValidationError("systemModelCredentialClearConfirmationMismatch");
          if (apiKey || secretRef) throw new UiValidationError("systemModelCredentialActionAmbiguous");
          payload.clear_credential = true;
          payload.credential_clear_confirmation = modelCredentialClearConfirmation;
        } else if (apiKey) {
          payload.api_key = apiKey;
          if (secretRef && secretRef !== (modal.model.raw?.api_key_secret_ref ?? "")) payload.api_key_secret_ref = secretRef;
        } else if (secretRef && secretRef !== (modal.model.raw?.api_key_secret_ref ?? "")) {
          payload.api_key_secret_ref = secretRef;
        }
        return await updateModel(apiFetch, modal.model.id, payload);
      } else {
        if (apiKey) payload.api_key = apiKey;
        if (secretRef) payload.api_key_secret_ref = secretRef;
        return await createModel(apiFetch, payload as AIModelPayload & { model_type: string });
      }
    }, (_result, current) => refreshModels(current), "systemModelSettingsUpdated");
  }

  return { modelDeleteDependencyLabel, runModelConnectionTest, refreshModels, activateModel, deactivateModelRow, openModelDeleteModal, submitModelDelete, openModelModal, toggleModelPair, submitModel };
}

export type ModelActions = ReturnType<typeof createModelActions>;

/** AI model view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createModelView(state: ModelState, actions: ModelActions, deps: Pick<WorkspaceViewDeps, "activeEmbeddingModels" | "apiFetch" | "canCreateModels" | "canDeleteModels" | "canEditModels" | "closeModal" | "discardModal" | "format" | "locale" | "localize" | "localizedOperationStatus" | "localizedStatus" | "modal" | "modalBlocked" | "modelTableFirst" | "modelTableLast" | "modelTableTotalPages" | "quickBlocked" | "refreshModelTable" | "runQuickMutation" | "sectionReady" | "setModal" | "submitting" | "t">) {
  const { modelTableRows, modelTableTotal, modelTableReceived, modelTablePage, setModelTablePage, modelTablePageSize, setModelTablePageSize, modelTableType, setModelTableType, modelTableLoading, modelTableError, modelDeleteConfirmation, setModelDeleteConfirmation, modelDeleteDependencies, modelProviderDraft, setModelProviderDraft, modelTypeDraft, setModelTypeDraft, modelPairDraft, modelCredentialClearDraft, setModelCredentialClearDraft, modelCredentialClearConfirmation, setModelCredentialClearConfirmation } = state;
  const { modelDeleteDependencyLabel, runModelConnectionTest, refreshModels, activateModel, deactivateModelRow, openModelDeleteModal, submitModelDelete, openModelModal, toggleModelPair, submitModel } = actions;

  function renderModelPanel() {
    const { apiFetch, canCreateModels, canDeleteModels, canEditModels, format, locale, localize, localizedOperationStatus, localizedStatus, modelTableFirst, modelTableLast, modelTableTotalPages, quickBlocked, refreshModelTable, runQuickMutation, sectionReady, setModal, t } = deps;
    return (
      <SettingsCard panel="models">
      <SectionHeader action={<button className="action-button" disabled={!canCreateModels || !sectionReady("models")} onClick={() => openModelModal()} type="button"><Bot size={16} />{t("systemAddModel")}</button>} description={t("systemModelsDescription")} title={t("systemModels")} />
      <div className="model-list-toolbar">
        <label><span>{t("systemModelTypeFilter")}</span><DropdownSelect aria-label={t("systemModelTypeFilter")} onChange={(event) => { setModelTableType(event.target.value); setModelTablePage(1); }} value={modelTableType}><option value="all">{t("systemAllModelTypes")}</option><option value="Chat">{t("labelChat")}</option><option value="Embedding">Embedding</option><option value="OCR">OCR</option><option value="Judge">Judge</option></DropdownSelect></label>
        <span aria-live="polite">{format("systemModelResultRange", { first: modelTableReceived ? modelTableFirst : t("systemReadCountUnknown"), last: modelTableReceived ? modelTableLast : t("systemReadCountUnknown"), total: modelTableReceived ? modelTableTotal : t("systemReadCountUnknown") })}</span>
      </div>
      {modelTableError ? <FeedbackMessage tone="error"><strong>{localize(modelTableError)}</strong><button className="icon-text-button" onClick={() => { void refreshModelTable(); }} type="button"><RefreshCw size={14} />{t("retry")}</button></FeedbackMessage> : null}
      {modelTableLoading ? <div className="system-table-loading" role="status"><LoaderCircle className="spin" size={20} /><span>{t("systemLoadingModels")}</span></div> : null}
      {!modelTableLoading && modelTableRows.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemName")}</th><th>{t("systemModelType")}</th><th>{t("labelProvider")}</th><th>{t("systemModel")}</th><th>{t("systemSecret")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{modelTableRows.map((model) => {
        const modelIsActive = model.status === "active";
        return <tr key={model.id}><td><strong>{model.name}</strong>{model.default ? <small>{format("systemDefaultModelLabel", { type: model.type })}</small> : null}</td><td>{model.type}</td><td>{model.provider}</td><td>{aiModelProviderName(model.raw?.config)}</td><td><span className="secret-state"><LockKeyhole size={14} />{model.raw?.api_key_configured || model.raw?.api_key_secret_ref ? t("systemConfigured") : t("systemNotConfigured")}</span></td><td><div className="model-status-stack"><StateBadge tone={modelIsActive ? "green" : "gold"}>{localizedStatus(model.status)}</StateBadge>{model.raw?.last_test_status ? <><StateBadge tone={model.raw.last_test_status === "success" ? "green" : model.raw.last_test_status === "failed" ? "coral" : "gold"}>{localizedOperationStatus(model.raw.last_test_status)}</StateBadge><small>{model.raw.last_tested_at ? formatDateTime(model.raw.last_tested_at, locale) : null}{model.raw.last_test_latency_ms !== null ? ` · ${model.raw.last_test_latency_ms} ms` : ""}</small></> : <small>{t("systemConnectionNotTested")}</small>}</div></td><td><div className="system-row-actions"><button className="icon-text-button" disabled={!canEditModels} onClick={() => openModelModal(model)} type="button">{t("systemEdit")}</button><button className="icon-text-button" disabled={!canEditModels || quickBlocked || model.default || !modelIsActive} onClick={() => { void runQuickMutation({ kind: "model", id: model.id, field: "is_default", value: true }, () => setDefaultModel(apiFetch, model.id), refreshModels); }} type="button">{t("systemSetDefault")}</button><button className="icon-text-button" disabled={!canEditModels} onClick={() => { void runModelConnectionTest(model); }} type="button">{t("systemTest")}</button>{modelIsActive ? <button className="icon-text-button" disabled={!canEditModels} onClick={() => setModal({ type: "confirm", title: t("systemDisableModel"), message: t("systemDisableModelHelp"), actionLabel: t("systemDisable"), successTitle: "systemModelDeactivated", target: { kind: "model", id: model.id, expected: { field: "is_active", value: false } }, run: accepted => deactivateModelRow(model, accepted) })} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={!canEditModels || quickBlocked} onClick={() => { void activateModel(model); }} type="button">{t("systemEnable")}</button>}<button aria-label={format("systemDeleteModelAria", { name: model.name })} className="icon-text-button destructive" disabled={!canDeleteModels} onClick={() => openModelDeleteModal(model)} type="button"><Trash2 size={14} />{t("systemDelete")}</button></div></td></tr>;
      })}</tbody></table></div> : null}
      {!modelTableLoading && !modelTableRows.length && !modelTableError ? <EmptyInlineState>{t("systemNoModelsMatchFilter")}</EmptyInlineState> : null}
      <div className="model-list-pagination">
        <label><span>{t("systemRowsPerPage")}</span><DropdownSelect aria-label={t("systemRowsPerPage")} onChange={(event) => { setModelTablePageSize(Number(event.target.value)); setModelTablePage(1); }} value={modelTablePageSize}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></DropdownSelect></label>
        <span>{format("systemPageOf", { page: modelTablePage, total: modelTableTotalPages })}</span>
        <div><button aria-label={t("systemPreviousPage")} className="icon-button" disabled={modelTableLoading || modelTablePage <= 1} onClick={() => setModelTablePage((page) => Math.max(1, page - 1))} type="button"><ChevronLeft size={17} /></button><button aria-label={t("systemNextPage")} className="icon-button" disabled={modelTableLoading || modelTablePage >= modelTableTotalPages} onClick={() => setModelTablePage((page) => Math.min(modelTableTotalPages, page + 1))} type="button"><ChevronRight size={17} /></button></div>
      </div>
    </SettingsCard>
    );
  }

  function renderModelForm(modal: Extract<ModalState, { type: "model" }>) {
    const { activeEmbeddingModels, canCreateModels, canEditModels, closeModal, discardModal, format, modalBlocked, submitting, t } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitModel(new FormData(event.currentTarget)); }}>
      <div className="system-security-note"><Settings2 size={17} /><div><strong>{format("labelProviderProfile", { provider: modelProviderDraft })}</strong><p>{t(providerHelpKey(modelProviderDraft))} {providerNeedsCredential(modelProviderDraft) ? t("systemProviderRequiresCredential") : t("systemProviderCredentialOptional")}</p></div></div>
      <div className="identity-form-grid">
        <label><span>{t("systemName")}</span><input defaultValue={modal.model?.name ?? ""} name="name" required /></label>
        <label><span>{t("systemModelType")}</span><DropdownSelect disabled={Boolean(modal.model)} name="model_type" onChange={(event) => { setModelTypeDraft(event.target.value); if (event.target.value === "OCR" && !modal.model) setModelProviderDraft("OpenAI"); }} value={modelTypeDraft}><option value="Chat">{t("labelChat")}</option><option>Embedding</option><option value="OCR">{t("labelPdfRecognition")}</option><option>Judge</option></DropdownSelect>{modal.model ? <input name="model_type" type="hidden" value={modal.model.type} /> : null}</label>
        <label><span>{t("labelProvider")}</span><DropdownSelect name="provider" onChange={(event) => setModelProviderDraft(event.target.value)} value={modelProviderDraft}>{aiProviders.filter((provider) => modelTypeDraft !== "OCR" || provider.id === "OpenAI" || provider.id === modal.model?.provider).map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</DropdownSelect></label>
        <label><span>{t("labelModelName")}</span><input defaultValue={modelConfigValue(modal.model, "model_name")} name="model_name" placeholder={modelProviderDraft === "Ollama" ? "llama3.1" : modelProviderDraft === "Gemini" ? "gemini-1.5-pro" : modelProviderDraft === "Claude" ? "claude-3-5-sonnet-latest" : t("systemModelNamePlaceholder")} required={modelProviderDraft !== "Custom"} /></label>
      </div>
      {modelProviderDraft === "OpenAI" ? <div className="identity-form-grid settings-child-fields">
        <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "https://api.openai.com/v1")} name="base_url" /></label>
        <label><span>{t("systemOrganizationIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "organization_id")} name="organization_id" /></label>
        <label><span>{t("systemProjectIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "project_id")} name="project_id" /></label>
        <OpenAiApiModeField existingMode={modelConfigValue(modal.model, "api_mode")} isExisting={Boolean(modal.model)} modelType={modelTypeDraft} />
        {modelTypeDraft === "Embedding" ? <label><span>{t("systemEmbeddingDimensionOptional")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_dimension")} min={1} name="embedding_dimension" type="number" /></label> : null}
      </div> : null}
      {modelProviderDraft === "Gemini" ? <div className="identity-form-grid settings-child-fields"><label><span>{t("labelApiVersion")}</span><input defaultValue={modelConfigValue(modal.model, "api_version", "v1beta")} name="api_version" /></label></div> : null}
      {modelProviderDraft === "Claude" ? <div className="identity-form-grid settings-child-fields">
        <label><span>{t("systemBaseUrlOptional")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "")} name="base_url" placeholder="https://api.anthropic.com" /></label>
        <label><span>Anthropic-Version</span><input defaultValue={modelConfigValue(modal.model, "anthropic_version", "2023-06-01")} name="anthropic_version" /></label>
      </div> : null}
      {modelProviderDraft === "Ollama" ? <div className="identity-form-grid settings-child-fields">
        <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "http://127.0.0.1:11434")} name="base_url" required /></label>
        <label><span>{t("labelTimeoutSeconds")}</span><input defaultValue={modelConfigValue(modal.model, "timeout_seconds", "120")} min={1} name="timeout_seconds" type="number" /></label>
      </div> : null}
      {modelProviderDraft === "vLLM" ? <div className="identity-form-grid settings-child-fields">
        <label><span>{t("labelOpenAiCompatibleBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "")} name="base_url" placeholder="http://127.0.0.1:8000/v1" required /></label>
        <label><span>{t("labelTimeoutSeconds")}</span><input defaultValue={modelConfigValue(modal.model, "timeout_seconds", "120")} min={1} name="timeout_seconds" type="number" /></label>
      </div> : null}
      {modelProviderDraft === "Custom" ? <>
        <label><span>{t("labelEndpoint")}</span><input defaultValue={modelConfigValue(modal.model, "endpoint", modal.model?.endpoint || "")} name="endpoint" required /></label>
        <div className="identity-form-grid"><label><span>{t("labelTimeoutSeconds")}</span><input defaultValue={modelConfigValue(modal.model, "timeout_seconds", "120")} min={1} name="timeout_seconds" type="number" /></label></div>
        <label><span>{t("systemHeadersJsonNoSecretLabel")}</span><textarea defaultValue={JSON.stringify(modal.model?.raw?.config?.headers ?? {}, null, 2)} name="headers_json" rows={3} /></label>
      </> : null}
      {modelTypeDraft === "Chat" ? <div className="system-model-pairing">
        <div className="system-model-pairing-header"><strong>{t("systemChatEmbeddingPairs")}</strong><p>{t("systemChatEmbeddingPairsHelp")}</p></div>
        {activeEmbeddingModels.length ? <details className="system-model-pair-dropdown"><summary><span className="system-model-pair-summary-main"><strong>{modelPairDraft.length ? format("systemChatEmbeddingPairsSelected", { count: modelPairDraft.length }) : t("systemChatEmbeddingPairsPlaceholder")}</strong><small>{format("systemChatEmbeddingPairsAvailable", { count: activeEmbeddingModels.length })}</small></span><ChevronDown size={16} /></summary><div className="system-model-pair-list">{activeEmbeddingModels.map((model) => {
          const selected = modelPairDraft.includes(model.id);
          return <label className={selected ? "system-model-pair-option selected" : "system-model-pair-option"} key={model.id}><input checked={selected} name="paired_embedding_model_ids" onChange={(event) => toggleModelPair(model.id, event.target.checked)} type="checkbox" value={model.id} /><span className="system-model-pair-option-main"><strong>{model.name}</strong><small>{model.provider}</small></span><span className="system-model-pair-endpoint">{model.endpoint ?? "—"}</span></label>;
        })}</div></details> : <EmptyInlineState>{t("systemNoEmbeddingModelsForPairing")}</EmptyInlineState>}
      </div> : null}
      <div className="system-model-pairing">
        <div className="system-model-pairing-header"><strong>{t("systemModelPricingTitle")}</strong><p>{t("systemModelPricingHelp")}</p></div>
        <div className="identity-form-grid">
          {(modelTypeDraft === "Chat" || modelTypeDraft === "Judge" || modelTypeDraft === "OCR") ? <>
            <label><span>{t("systemModelInputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "input_cost_per_million_tokens")} min="0" name="input_cost_per_million_tokens" step="any" type="number" /></label>
            <label><span>{t("systemModelOutputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "output_cost_per_million_tokens")} min="0" name="output_cost_per_million_tokens" step="any" type="number" /></label>
          </> : null}
          {modelTypeDraft === "Embedding" ? <label><span>{t("systemModelEmbeddingPrice")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_cost_per_million_tokens")} min="0" name="embedding_cost_per_million_tokens" step="any" type="number" /></label> : null}
          <label><span>{t("systemModelCostCurrency")}</span><DropdownSelect defaultValue={modelConfigValue(modal.model, "cost_currency")} name="cost_currency"><option value="">{t("systemModelCostCurrencyPlaceholder")}</option>{["TWD", "USD", "JPY", "EUR", "GBP", "CNY", "HKD", "SGD", "AUD", "CAD", "KRW"].map((currency) => <option key={currency}>{currency}</option>)}</DropdownSelect></label>
        </div>
      </div>
      <label><span>{t("systemApiKeyRetainExisting")}</span><input autoComplete="new-password" disabled={modelCredentialClearDraft} name="api_key" type="password" /></label>
      <label><span>{t("labelSecretReference")}</span><input defaultValue={modal.model?.raw?.api_key_secret_ref ?? ""} disabled={modelCredentialClearDraft} name="api_key_secret_ref" placeholder={t("systemSecretReferencePlaceholder")} /></label>
      <AIModelCredentialClearControl clearDraft={modelCredentialClearDraft} configured={Boolean(modal.model?.raw?.api_key_configured)} confirmation={modelCredentialClearConfirmation} modelName={modal.model?.name ?? ""} onClearChange={(checked) => { setModelCredentialClearDraft(checked); setModelCredentialClearConfirmation(""); }} onConfirmationChange={setModelCredentialClearConfirmation} />
      {modelTypeDraft === "OCR" && modelProviderDraft === "OpenAI" ? <fieldset className="native-pdf-capability-form"><legend>{t("nativePdfCapabilitiesTitle")}</legend><small>{t("nativePdfCapabilitiesHelp")}</small><div className="identity-form-grid">
        <label><span>{t("nativePdfProtocol")}</span><input readOnly value="openai_responses" /></label><label><span>{t("nativePdfMime")}</span><input readOnly value="application/pdf" /></label>
        {nativePdfLimitFields.map((key) => <label key={key}><span>{t(nativePdfLimitLabels[key])}</span><input defaultValue={typeof nativePdfProfile(modal.model)[key] === "number" ? String(nativePdfProfile(modal.model)[key]) : ""} min={1} name={`native_pdf_${key}`} step={1} type="number" /></label>)}
        <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).supports_pdf === true} name="native_pdf_supports_pdf" type="checkbox" /><span>{t("nativePdfSupportsPdf")}</span></label>
        <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).count_input_tokens === true} name="native_pdf_count_input_tokens" type="checkbox" /><span>{t("nativePdfSupportsCount")}</span></label>
        <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).supports_temperature === true} name="native_pdf_supports_temperature" type="checkbox" /><span>{t("nativePdfSupportsTemperature")}</span></label>
      </div></fieldset> : null}
      <label><span>{t("systemAdvancedConfigJson")}</span><textarea defaultValue={JSON.stringify(Object.fromEntries(Object.entries(modal.model?.raw?.config ?? {}).filter(([key]) => modelTypeDraft !== "OCR" || key !== "native_pdf")), null, 2)} name="config_advanced" rows={5} /><small>{t("systemAdvancedConfigHelp")}</small>{modelTypeDraft === "Embedding" ? <small>{t("systemEmbeddingCapacityHelp")}</small> : null}{modelTypeDraft === "OCR" ? <><small>{t("systemNativePdfProviderHelp")}</small><small>{t("systemNativePdfProfileHelp")}</small></> : null}</label>
      <label className="identity-toggle"><input defaultChecked={modal.model?.status !== "inactive"} name="is_active" type="checkbox" /><span>{t("systemEnable")}</span></label>
      <label className="identity-toggle"><input defaultChecked={modal.model?.default ?? false} name="is_default" type="checkbox" /><span>{t("systemSetTypeDefault")}</span></label>
      <footer><button className="action-button secondary" onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={submitting || (!modal.model && !canCreateModels) || (Boolean(modal.model) && !canEditModels) || (modelCredentialClearDraft && modelCredentialClearConfirmation !== modal.model?.name)} type="submit">{modal.model ? <Save size={16} /> : <Plus size={16} />}{modal.model ? t("systemSaveModel") : t("systemAddModel")}</button></footer>
    </FeedbackForm>
    );
  }

  function renderModelDeleteForm(modal: Extract<ModalState, { type: "model-delete" }>) {
    const { closeModal, format, localizedStatus, modalBlocked, submitting, t } = deps;
    return (
      <div className="system-crud-form model-delete-content">
      <FeedbackMessage tone="warning"><div><strong>{t("systemDeleteModelWarningTitle")}</strong><p>{t("systemDeleteModelWarningHelp")}</p></div></FeedbackMessage>
      <div className="system-detail-grid"><div><small>{t("systemModel")}</small><strong>{modal.model.name}</strong></div><div><small>{t("systemModelType")}</small><strong>{modal.model.type}</strong></div><div><small>{t("labelProvider")}</small><strong>{modal.model.provider}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.model.status)}</strong></div></div>
      {modelDeleteDependencies.length ? <section className="model-delete-dependencies"><strong>{t("systemDeleteModelBlockedTitle")}</strong><p>{t("systemDeleteModelBlockedHelp")}</p><ul>{modelDeleteDependencies.map((dependency) => <li key={dependency.type}><span>{modelDeleteDependencyLabel(dependency.type)}</span><strong>{dependency.count}</strong></li>)}</ul></section> : null}
      <label><span>{format("systemDeleteModelConfirmationLabel", { name: modal.model.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setModelDeleteConfirmation(event.target.value)} placeholder={modal.model.name} value={modelDeleteConfirmation} /><small>{t("systemDeleteModelConfirmationHelp")}</small></label>
      <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked || modelDeleteConfirmation !== modal.model.name} onClick={() => { void submitModelDelete(modal.model); }} type="button"><Trash2 size={16} />{t("systemDeleteModelPermanently")}</button></footer>
    </div>
    );
  }

  return { renderModelPanel, renderModelForm, renderModelDeleteForm };
}
