"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { createModel, deleteModel, testModel, updateModel, type AIModelPayload, type ApiError, type ApiFetch } from "@/lib/api";
import { UiValidationError } from "@/lib/transportError";
import { containsSecretConfigKey, modelRow, nativePdfConfigFromForm, normalizedProvider, pairedEmbeddingModelIds, type ModelDeleteDependency } from "./modelHelpers";
import type { FeedbackMessage } from "@/lib/feedback";
import type { TranslationKey } from "@/lib/i18nClient";
import type { ModalState, ModelRow } from "./modalState";

export type QuickMutationTarget = { kind: "model" | "role"; id: string; field: "is_active" | "is_default"; value: boolean };

/** Workspace dependencies shared with the model section. */
export type ModelDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  modal: ModalState | null;
  notify: (message: FeedbackMessage, toast?: boolean) => void;
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
