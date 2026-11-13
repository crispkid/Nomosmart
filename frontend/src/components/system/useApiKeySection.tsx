"use client";

import { useState, type Dispatch, type SetStateAction } from "react";
import { KeyRound, Plus, RefreshCw, RotateCcw, Save, Search, Settings2 } from "lucide-react";
import { FeedbackForm } from "@/components/FeedbackForm";
import { FeedbackField } from "@/components/FeedbackMessage";
import { SettingsCard } from "../SettingsCard";
import { EmptyInlineState, SectionHeader, StateBadge } from "./SystemUi";
import { activateIntegrationClient, createIntegrationClient, deactivateIntegrationClient, getProject, replaceIntegrationClientProjectScopes, revokeIntegrationClient, rotateIntegrationClientKey, updateIntegrationClient, type ApiFetch, type IntegrationClientResponse, type ProjectResponse } from "@/lib/api";
import { IntegrationClientDateError, integrationClientDateInput, integrationClientDateUpdate, integrationClientDateValue } from "@/lib/integrationClientDates";
import { MutationOutcomeUnknown } from "@/lib/transportError";
import type { TranslationKey } from "@/lib/i18nClient";
import { modalScope, type ModalState } from "./modalState";
import type { WorkspaceViewDeps } from "./viewDeps";

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

export type ApiKeyActions = ReturnType<typeof createApiKeyActions>;

/** API key view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createApiKeyView(state: ApiKeyState, actions: ApiKeyActions, deps: Pick<WorkspaceViewDeps, "activeProjects" | "canCreateSystemManagement" | "canDeleteSystemManagement" | "canEditSystemManagement" | "clientNextCursor" | "closeModal" | "discardModal" | "format" | "modal" | "modalBlocked" | "projectNameById" | "renderListPager" | "renderProjectSearch" | "renderSectionReadNotice" | "sectionReady" | "setModal" | "submitting" | "t">) {
  const { integrationClients, apiKeyProjectDraft, apiKeyScopeDrafts, clientQuery, setClientQuery, clientCursors, setClientCursors, clientPageSize, setClientPageSize } = state;
  const { refreshIntegrationClients, toggleApiKeyProjectDraft, toggleApiKeyScopeDraft, renderApiKeyDateField, openApiKeyCreateModal, openApiKeyManageModal, submitApiKey, saveApiKeyManagement, rotateApiKey, setApiKeyStatus, revokeApiKey, apiKeyStatusLabel } = actions;

  function renderApiKeyPanel() {
    const { canCreateSystemManagement, clientNextCursor, format, projectNameById, renderListPager, sectionReady, t } = deps;
    return (
      <SettingsCard panel="clients">
      <SectionHeader
        action={<div className="system-section-actions"><button className="action-button secondary" onClick={() => { void refreshIntegrationClients(); }} type="button"><RefreshCw size={16} />{t("refresh")}</button><button className="action-button" disabled={!canCreateSystemManagement || !sectionReady("projects") || !sectionReady("clients")} onClick={openApiKeyCreateModal} type="button"><Plus size={16} />{t("systemApiKeyCreateTitle")}</button></div>}
        description={t("systemApiKeysDescription")}
        title={t("systemApiKeys")}
      />
      <section className="system-api-key-list">
        <div className="system-subsection-title"><div><h3>{t("systemApiKeyListTitle")}</h3><p>{t("systemApiKeyListHelp")}</p></div></div>
        <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("adminSearchClients")} maxLength={255} onChange={event => { setClientQuery(event.target.value); setClientCursors([undefined]); }} placeholder={t("adminSearchClients")} value={clientQuery} /></label></div>
        {renderListPager("clients", clientCursors.length, clientPageSize, null, () => setClientCursors(cursors => cursors.slice(0, -1)), clientNextCursor ? () => setClientCursors(cursors => [...cursors, clientNextCursor]) : null, size => { setClientPageSize(size); setClientCursors([undefined]); })}
        {integrationClients.length ? <div className="system-api-key-rows">{integrationClients.map((client) => {
          const authorizedProjectNames = client.project_ids.map((projectId) => projectNameById.get(projectId) ?? projectId);
          const projectSummary = authorizedProjectNames.length ? authorizedProjectNames.slice(0, 3).join(", ") + (authorizedProjectNames.length > 3 ? ` +${authorizedProjectNames.length - 3}` : "") : t("systemApiKeyNoProjects");
          return <article className="system-api-key-row" key={client.id}>
            <header><div><strong>{client.name}</strong><small>{format("systemApiKeyVersionIdentity", { prefix: client.api_key_prefix, version: client.api_key_version })}</small></div><StateBadge tone={apiKeyStatusTone(client)}>{apiKeyStatusLabel(client)}</StateBadge></header>
            <p>{client.description || t("systemApiKeyNoDescription")}</p>
            <dl className="system-api-key-metrics"><div><dt>{t("systemApiKeySuccessCount")}</dt><dd>{client.success_count}</dd></div><div><dt>{t("systemApiKeyFailureCount")}</dt><dd>{client.failure_count}</dd></div><div><dt>{t("systemApiKeyLastUsed")}</dt><dd>{client.last_used_at ? client.last_used_at.slice(0, 16).replace("T", " ") : "—"}</dd></div><div><dt>{t("systemApiKeyExpiresAt")}</dt><dd>{client.expires_at ? client.expires_at.slice(0, 16).replace("T", " ") : t("systemApiKeyNoExpiry")}</dd></div><div><dt>{t("systemApiKeyAuthorizedProjects")}</dt><dd>{format("systemApiKeyAuthorizedProjectsValue", { count: client.project_ids.length })}</dd></div></dl>
            <div className="system-api-key-scope-summary"><span>{t("systemApiKeyProjectScopes")}</span><strong>{projectSummary}</strong></div>
            <footer><button className="icon-text-button" onClick={() => openApiKeyManageModal(client)} type="button"><Settings2 size={15} />{t("systemApiKeyManage")}</button></footer>
          </article>;
        })}</div> : sectionReady("clients") ? <EmptyInlineState>{t("systemApiKeyEmpty")}</EmptyInlineState> : null}
      </section>
    </SettingsCard>
    );
  }

  function renderApiKeyCreateForm() {
    const { activeProjects, canCreateSystemManagement, closeModal, discardModal, modal, modalBlocked, renderProjectSearch, renderSectionReadNotice, sectionReady, submitting, t } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void submitApiKey(new FormData(event.currentTarget)); }}>
      <p className="system-modal-help">{t("systemApiKeyCreateHelp")}</p>
      <div className="identity-form-grid">
        <label><span>{t("systemName")}</span><input name="name" placeholder={t("systemApiKeyNamePlaceholder")} required /></label>
        <label><span>{t("systemApiKeyRequestsPerMinute")}</span><input defaultValue={60} min={1} name="requests_per_minute" type="number" /></label>
        {renderApiKeyDateField("valid_from")}
        {renderApiKeyDateField("expires_at")}
        <label><span>{t("systemApiKeyContactName")}</span><input name="contact_name" /></label>
        <label><span>{t("systemApiKeyContactEmail")}</span><input name="contact_email" type="email" /></label>
        <label><span>{t("systemApiKeyContactDepartment")}</span><input name="contact_department" /></label>
        <label className="identity-wide-field"><span>{t("systemDescription")}</span><textarea name="description" rows={3} /></label>
      </div>
      <div className="system-api-project-picker">{renderSectionReadNotice("projects")}{renderProjectSearch()}<strong>{t("systemApiKeyProjectScopes")}</strong><p>{t("systemApiKeyProjectScopesHelp")}</p>{activeProjects.length ? <div>{activeProjects.map((project) => <label className={apiKeyProjectDraft.includes(project.id) ? "active" : ""} key={project.id}><input checked={apiKeyProjectDraft.includes(project.id)} disabled={!sectionReady("projects")} onChange={(event) => toggleApiKeyProjectDraft(project.id, event.target.checked)} type="checkbox" /> <span>{project.name}</span></label>)}</div> : sectionReady("projects") ? <EmptyInlineState>{t("systemApiKeyNoProjects")}</EmptyInlineState> : null}</div>
      <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={!canCreateSystemManagement || submitting || !apiKeyProjectDraft.length} type="submit"><Plus size={16} />{t("systemApiKeyCreate")}</button></footer>
    </FeedbackForm>
    );
  }

  function renderApiKeyManageForm(modal: Extract<ModalState, { type: "api-key-manage" }>) {
    const { activeProjects, canDeleteSystemManagement, canEditSystemManagement, closeModal, discardModal, format, modalBlocked, projectNameById, renderProjectSearch, renderSectionReadNotice, sectionReady, setModal, submitting, t } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void saveApiKeyManagement(modal.client, new FormData(event.currentTarget)); }}>
      <div className="system-security-note"><KeyRound size={17} /><div><strong>{format("systemApiKeyVersionIdentity", { prefix: modal.client.api_key_prefix, version: modal.client.api_key_version })}</strong><p>{t("systemApiKeyManageHelp")}</p></div><StateBadge tone={apiKeyStatusTone(modal.client)}>{apiKeyStatusLabel(modal.client)}</StateBadge></div>
      <div className="identity-form-grid">
        <label><span>{t("systemName")}</span><input defaultValue={modal.client.name} disabled={modal.client.status === "revoked"} name="name" required /></label>
        <label><span>{t("systemApiKeyRequestsPerMinute")}</span><input defaultValue={modal.client.requests_per_minute ?? 60} disabled={modal.client.status === "revoked"} min={1} name="requests_per_minute" type="number" /></label>
        {renderApiKeyDateField("valid_from", modal.client.valid_from, modal.client.status === "revoked")}
        {renderApiKeyDateField("expires_at", modal.client.expires_at, modal.client.status === "revoked")}
        <label><span>{t("systemApiKeyContactName")}</span><input defaultValue={modal.client.contact_name ?? ""} disabled={modal.client.status === "revoked"} name="contact_name" /></label>
        <label><span>{t("systemApiKeyContactEmail")}</span><input defaultValue={modal.client.contact_email ?? ""} disabled={modal.client.status === "revoked"} name="contact_email" type="email" /></label>
        <label><span>{t("systemApiKeyContactDepartment")}</span><input defaultValue={modal.client.contact_department ?? ""} disabled={modal.client.status === "revoked"} name="contact_department" /></label>
        <label className="identity-wide-field"><span>{t("systemDescription")}</span><textarea defaultValue={modal.client.description ?? ""} disabled={modal.client.status === "revoked"} name="description" rows={3} /></label>
      </div>
      <div className="system-api-project-picker">{renderSectionReadNotice("projects")}{renderProjectSearch()}<strong>{t("systemApiKeyProjectScopes")}</strong><p>{t("systemApiKeyProjectScopesHelp")}</p>{activeProjects.length ? <div>{activeProjects.map((project) => {
        const scopeDraft = apiKeyScopeDrafts[modal.client.id] ?? modal.client.project_ids;
        return <label className={scopeDraft.includes(project.id) ? "active" : ""} key={project.id}><input checked={scopeDraft.includes(project.id)} disabled={modal.client.status === "revoked" || !canEditSystemManagement || submitting || !sectionReady("projects")} onChange={(event) => toggleApiKeyScopeDraft(modal.client.id, project.id, event.target.checked)} type="checkbox" /> <span>{projectNameById.get(project.id) ?? project.name}</span></label>;
      })}</div> : sectionReady("projects") ? <EmptyInlineState>{t("systemApiKeyNoProjects")}</EmptyInlineState> : null}</div>
      <div className="system-api-key-modal-actions">
        <button className="icon-text-button" disabled={modal.client.status === "revoked" || !canEditSystemManagement || submitting} onClick={() => { void rotateApiKey(modal.client); }} type="button"><RotateCcw size={15} />{t("systemApiKeyRotate")}</button>
        {modal.client.status === "active" ? <button className="icon-text-button" disabled={!canEditSystemManagement || submitting} onClick={() => { void setApiKeyStatus(modal.client, false); }} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={modal.client.status === "revoked" || !canEditSystemManagement || modal.client.effective_status === "expired" || submitting} onClick={() => { void setApiKeyStatus(modal.client, true); }} type="button">{t("systemEnable")}</button>}
        <button className="icon-text-button danger" disabled={modal.client.status === "revoked" || !canDeleteSystemManagement || submitting} onClick={() => setModal({ type: "confirm", title: t("systemApiKeyRevoke"), message: format("systemApiKeyRevokeConfirm", { name: modal.client.name }), actionLabel: t("systemApiKeyRevoke"), successTitle: "systemApiKeyRevoked", target: { kind: "client", id: modal.client.id, expected: { field: "status", value: "revoked" } }, run: accepted => revokeApiKey(modal.client, accepted) })} type="button">{t("systemApiKeyRevoke")}</button>
      </div>
      <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={!canEditSystemManagement || submitting || modal.client.status === "revoked"} type="submit"><Save size={16} />{t("save")}</button></footer>
    </FeedbackForm>
    );
  }

  function apiKeyStatusTone(client: IntegrationClientResponse): "green" | "gold" | "gray" | "coral" {
    if (client.status === "revoked") return "coral";
    if (client.effective_status === "expired" || client.effective_status === "scheduled") return "gold";
    return client.status === "active" ? "green" : "gray";
  }

  return { renderApiKeyPanel, renderApiKeyCreateForm, renderApiKeyManageForm, apiKeyStatusTone };
}
