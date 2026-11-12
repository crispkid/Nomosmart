"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { FeedbackField } from "@/components/FeedbackMessage";
import { activateIntegrationClient, createIntegrationClient, deactivateIntegrationClient, getProject, listIntegrationClientsPage, replaceIntegrationClientProjectScopes, revokeIntegrationClient, rotateIntegrationClientKey, updateIntegrationClient, type ApiFetch, type IntegrationClientResponse, type ProjectResponse } from "@/lib/api";
import { IntegrationClientDateError, integrationClientDateInput, integrationClientDateUpdate, integrationClientDateValue } from "@/lib/integrationClientDates";
import { MutationOutcomeUnknown } from "@/lib/transportError";
import type { TranslationKey } from "@/lib/i18nClient";
import { modalScope, type ModalState } from "./modalState";

/** Dependencies shared with the rest of the workspace, read when a handler runs. */
export type ApiKeySectionDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  format: (key: TranslationKey, params: Record<string, string | number>) => string;
  modal: ModalState | null;
  setModal: (next: SetStateAction<ModalState | null>) => void;
  setModalError: Dispatch<SetStateAction<string>>;
  setModalQueryMessage: Dispatch<SetStateAction<string>>;
  systemReadScope: string;
  /** Current read scope, read when a handler runs (never during render). */
  readScopeNow: () => string | null;
  cacheProjects: (rows: ProjectResponse[]) => void;
  readSystemSection: <T>(section: string, read: () => Promise<T>, apply: (value: T) => void, outerCurrent?: () => boolean) => Promise<boolean>;
  reloadSystemSection: (section: string, current?: () => boolean) => Promise<boolean>;
  runModalMutation: <T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title?: TranslationKey) => Promise<void>;
  sectionReady: (section: string) => boolean;
};

export type ApiKeyState = ReturnType<typeof useApiKeyState>;

/** Integration client (API key) state (OPT424-038). */
export function useApiKeyState() {
  const [integrationClients, setIntegrationClients] = useState<IntegrationClientResponse[]>([]);
  const [apiKeyDateValidation, setApiKeyDateValidation] = useState<{ scope: string; errors: Partial<Record<"valid_from" | "expires_at", TranslationKey>> }>({ scope: "", errors: {} });
  const [apiKeyProjectDraft, setApiKeyProjectDraft] = useState<string[]>([]);
  const [apiKeyScopeDrafts, setApiKeyScopeDrafts] = useState<Record<string, string[]>>({});
  const [apiKeyOneTime, setApiKeyOneTime] = useState<{ name: string; key: string } | null>(null);
  const [clientQuery, setClientQuery] = useState("");
  const [clientCursors, setClientCursors] = useState<(string | undefined)[]>([undefined]);
  const [clientPageSize, setClientPageSize] = useState(20);
  return { integrationClients, setIntegrationClients, apiKeyDateValidation, setApiKeyDateValidation, apiKeyProjectDraft, setApiKeyProjectDraft, apiKeyScopeDrafts, setApiKeyScopeDrafts, apiKeyOneTime, setApiKeyOneTime, clientQuery, setClientQuery, clientCursors, setClientCursors, clientPageSize, setClientPageSize };
}

/** Integration client (API key) actions; created each render once workspace dependencies exist. */
export function createApiKeyActions(state: ApiKeyState, deps: ApiKeySectionDeps) {
  const { integrationClients, setIntegrationClients, apiKeyDateValidation, setApiKeyDateValidation, apiKeyProjectDraft, setApiKeyProjectDraft, apiKeyScopeDrafts, setApiKeyScopeDrafts, apiKeyOneTime, setApiKeyOneTime, clientQuery, setClientQuery, clientCursors, setClientCursors, clientPageSize, setClientPageSize } = state;

  async function refreshIntegrationClients(current?: () => boolean) {
    const { reloadSystemSection } = deps;
    const valid = current ?? (() => true);
    const success = await reloadSystemSection("clients", valid);
    if (current && valid() && !success) throw new Error("System read could not be confirmed");
  }

  function toggleApiKeyProjectDraft(projectId: string, checked: boolean) {
    setApiKeyProjectDraft((current) => checked ? [...new Set([...current, projectId])] : current.filter((id) => id !== projectId));
  }

  function toggleApiKeyScopeDraft(clientId: string, projectId: string, checked: boolean) {
    setApiKeyScopeDrafts((current) => {
      const existing = current[clientId] ?? [];
      return { ...current, [clientId]: checked ? [...new Set([...existing, projectId])] : existing.filter((id) => id !== projectId) };
    });
  }

  function apiDateValues(formData: FormData, original?: IntegrationClientResponse) {
    const { t, modal, setModalError } = deps;
    const dates: Partial<Record<"valid_from" | "expires_at", string | null>> = {};
    const errors: Partial<Record<"valid_from" | "expires_at", TranslationKey>> = {};
    for (const key of ["valid_from", "expires_at"] as const) {
      try {
        const value = String(formData.get(key) ?? "").trim();
        const date = original ? integrationClientDateUpdate(value, original[key]) : integrationClientDateValue(value);
        if (date !== undefined) dates[key] = date;
      } catch (error) {
        errors[key] = error instanceof IntegrationClientDateError && error.reason === "ambiguous" ? "systemApiKeyDateAmbiguous" : error instanceof IntegrationClientDateError && error.reason === "unavailable" ? "systemApiKeyDateUnavailable" : "systemApiKeyDateInvalid";
      }
    }
    setApiKeyDateValidation({ scope: modalScope(modal), errors });
    if (Object.keys(errors).length) { setModalError(t("systemApiKeyDateFix")); return null; }
    return dates;
  }

  function renderApiKeyDateField(key: "valid_from" | "expires_at", original: string | null = null, disabled = false) {
    const { t, format, modal } = deps;
    const baseline = integrationClientDateInput(original);
    const error = baseline === null ? "systemApiKeyDateUnavailable" : apiKeyDateValidation.scope === modalScope(modal) ? apiKeyDateValidation.errors[key] : undefined;
    const id = `api-key-date-${key}`;
    return <label className={error ? "has-error" : undefined}>
      <span>{t(key === "valid_from" ? "systemApiKeyValidFrom" : "systemApiKeyExpiresAt")}</span>
      <input aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`} aria-invalid={Boolean(error)} defaultValue={baseline ?? ""} disabled={disabled || baseline === null} name={key} type="datetime-local" onChange={() => setApiKeyDateValidation(current => ({ scope: modalScope(modal), errors: { ...(current.scope === modalScope(modal) ? current.errors : {}), [key]: undefined } }))} />
      <small id={`${id}-help`}>{format("systemApiKeyDateTimezone", { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })}</small>
      {error ? <FeedbackField id={`${id}-error`}>{t(error)}</FeedbackField> : null}
    </label>;
  }

  function sameApiKeyScope(left: string[], right: string[]) {
    return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
  }

  function syncIntegrationClient(updated: IntegrationClientResponse) {
    const { setModal } = deps;
    setIntegrationClients((current) => current.map((item) => item.id === updated.id ? updated : item));
    setApiKeyScopeDrafts((current) => ({ ...current, [updated.id]: updated.project_ids }));
    setModal((current) => current?.type === "api-key-manage" && current.client.id === updated.id ? { ...current, client: updated } : current);
  }

  function openApiKeyCreateModal() {
    const { setModal, setModalError } = deps;
    setApiKeyProjectDraft([]);
    setModalError("");
    setModal({ type: "api-key-create" });
  }

  function openApiKeyManageModal(client: IntegrationClientResponse) {
    const { apiFetch, setModal, setModalError, systemReadScope, readScopeNow, cacheProjects, readSystemSection } = deps;
    const scope = systemReadScope;
    void readSystemSection("selectedProjects", () => Promise.all(client.project_ids.map(id => getProject(apiFetch, id))), cacheProjects, () => readScopeNow() === scope);

    setApiKeyScopeDrafts((current) => ({ ...current, [client.id]: client.project_ids }));
    setModalError("");
    setModal({ type: "api-key-manage", client });
  }

  async function submitApiKey(formData: FormData) {
    const { apiFetch, t, setModalError, runModalMutation, sectionReady } = deps;
    if (!sectionReady("projects")) { setModalError(t("systemReadUnknown")); return; }
    const dates = apiDateValues(formData); if (!dates) return;
    if (!apiKeyProjectDraft.length) { setModalError(t("systemApiKeyProjectRequired")); return; }
    await runModalMutation(() => createIntegrationClient(apiFetch, {
      name: String(formData.get("name") || "").trim(), description: String(formData.get("description") || "").trim() || null,
      contact_name: String(formData.get("contact_name") || "").trim() || null, contact_email: String(formData.get("contact_email") || "").trim() || null,
      contact_department: String(formData.get("contact_department") || "").trim() || null,
      ...dates,
      requests_per_minute: Number(formData.get("requests_per_minute") || 60), project_ids: apiKeyProjectDraft
    }), async (created, current) => {
      setApiKeyOneTime({ name: created.name, key: created.api_key }); setApiKeyProjectDraft([]);
      await refreshIntegrationClients(current);
    }, "systemApiKeyCreated");
  }

  async function saveApiKeyManagement(client: IntegrationClientResponse, formData: FormData) {
    const { apiFetch, t, setModalError, setModalQueryMessage, runModalMutation } = deps;
    const dates = apiDateValues(formData, client); if (!dates) return;
    const projectIds = apiKeyScopeDrafts[client.id] ?? client.project_ids;
    if (!projectIds.length) { setModalError(t("systemApiKeyProjectRequired")); return; }
    await runModalMutation(async (_accepted, current) => {
      const updated = await updateIntegrationClient(apiFetch, client.id, {
        lock_version: client.lock_version, name: String(formData.get("name") || "").trim(),
        description: String(formData.get("description") || "").trim() || null, contact_name: String(formData.get("contact_name") || "").trim() || null,
        contact_email: String(formData.get("contact_email") || "").trim() || null, contact_department: String(formData.get("contact_department") || "").trim() || null,
        ...dates, requests_per_minute: Number(formData.get("requests_per_minute") || 60)
      });
      if (!current()) throw new DOMException("", "AbortError");
      if (sameApiKeyScope(projectIds, updated.project_ids)) return updated;
      try { return await replaceIntegrationClientProjectScopes(apiFetch, client.id, { lock_version: updated.lock_version, project_ids: projectIds }); }
      catch { if (current()) setModalQueryMessage(t("feedbackPartialUpdate")); throw new MutationOutcomeUnknown(); }
    }, syncIntegrationClient, "systemApiKeyUpdated");
  }

  async function rotateApiKey(client: IntegrationClientResponse) {
    const { apiFetch, runModalMutation } = deps;
    await runModalMutation(() => rotateIntegrationClientKey(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_rotate" }), async (rotated, current) => {
      setApiKeyOneTime({ name: rotated.name, key: rotated.api_key }); await refreshIntegrationClients(current);
    }, "systemApiKeyRotated");
  }

  async function setApiKeyStatus(client: IntegrationClientResponse, active: boolean) {
    const { apiFetch, runModalMutation } = deps;
    await runModalMutation(() => active ? activateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_activate" }) : deactivateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_deactivate" }), syncIntegrationClient);
  }

  async function revokeApiKey(client: IntegrationClientResponse, accepted: () => void) {
    const { apiFetch } = deps;
    const updated = await revokeIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_revoke" });
    accepted(); syncIntegrationClient(updated);
  }

  function apiKeyStatusLabel(client: IntegrationClientResponse) {
    const { t } = deps;
    if (client.effective_status === "expired") return t("systemApiKeyExpired");
    if (client.effective_status === "scheduled") return t("systemApiKeyScheduled");
    if (client.status === "revoked") return t("systemApiKeyRevokedStatus");
    return client.status === "active" ? t("systemEnabled") : t("systemDisabled");
  }

  return { refreshIntegrationClients, toggleApiKeyProjectDraft, toggleApiKeyScopeDraft, apiDateValues, renderApiKeyDateField, sameApiKeyScope, syncIntegrationClient, openApiKeyCreateModal, openApiKeyManageModal, submitApiKey, saveApiKeyManagement, rotateApiKey, setApiKeyStatus, revokeApiKey, apiKeyStatusLabel };
}
