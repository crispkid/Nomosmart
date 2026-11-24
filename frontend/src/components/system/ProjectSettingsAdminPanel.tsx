"use client";

import { useCallback, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Cpu, ListFilter, RefreshCw, UserMinus, UserPlus, UsersRound, X } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { SettingsCard } from "@/components/SettingsCard";
import { useAuth } from "@/components/AuthProvider";
import { StateBadge } from "@/components/system/SystemUi";
import {
  batchProjectSettings, getProjectSettings, listModels, listProjectSettings, listUsersPage,
  type AIModelResponse, type ApiFetch, type ProjectSettingsBatch, type ProjectSettingsItem, type ProjectSettingsResult, type UserSummary
} from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { useReadResource } from "@/lib/useReadResource";

const PAGE_SIZE = 50;
const ROLES = ["owner", "editor", "viewer"] as const;
type Dialog = "models" | "put_member" | "remove_member" | null;
const REASONS: Record<string, TranslationKey> = {
  project_archived: "projectSettingsReasonArchived", project_not_found: "projectSettingsReasonNotFound",
  last_project_owner: "projectSettingsReasonLastOwner", project_model_configuration_required: "projectSettingsReasonModels",
  stale_project_version: "projectSettingsReasonChanged"
};

/** CHG-486 PSET486-001..006: every project's models, members and rerank switch, changed for one or many projects. */
export function ProjectSettingsAdminPanel() {
  const { apiFetch, can } = useAuth();
  const { t, format } = useI18n();
  const allowed = can("Menu", "SystemManagement", "view");
  const editable = can("Menu", "SystemManagement", "edit");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"active" | "archived">("active");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [detail, setDetail] = useState<ProjectSettingsItem | null>(null);
  const [results, setResults] = useState<{ action: string; rows: ProjectSettingsResult[] } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const read = useCallback((signal: AbortSignal) => listProjectSettings(apiFetch, { q: search, status, offset, limit: PAGE_SIZE, signal }), [apiFetch, search, status, offset]);
  const page = useReadResource(read, `project-settings:${status}:${search}:${offset}`, allowed, { keepData: true });
  const rows = useMemo(() => page.data?.items ?? [], [page.data]);
  const names = useMemo(() => new Map(rows.map(row => [row.id, row.name])), [rows]);
  if (!allowed) return null;
  const archivedView = status === "archived";
  const canChange = editable && !archivedView;
  const allSelected = rows.length > 0 && rows.every(row => selected.includes(row.id));

  async function run(payload: ProjectSettingsBatch) {
    setBusy(true); setError("");
    try {
      const rowsOut = await batchProjectSettings(apiFetch, payload);
      setResults({ action: payload.action, rows: rowsOut }); setDialog(null); page.reload();
    } catch (failure) {
      setError(operationalErrorMessage(failure, t, format, "projectSettingsActionFailed"));
    } finally { setBusy(false); }
  }
  async function openDetail(row: ProjectSettingsItem) {
    try { setDetail(await getProjectSettings(apiFetch, row.id)); }
    catch (failure) { setError(operationalErrorMessage(failure, t, format, "projectSettingsLoadFailed")); }
  }
  const modelName = (model: ProjectSettingsItem["llm_model"]) => model?.name ?? <span className="field-note">{t("projectSettingsNotSet")}</span>;

  return <SettingsCard panel="project-settings" title={t("settingsProjectSettings")} description={t("projectSettingsHelp")}>
    <div className="system-toolbar compact project-settings-toolbar">
      <form onSubmit={event => { event.preventDefault(); setOffset(0); setSelected([]); setSearch(query); }}>
        <label><span>{t("projectSettingsSearch")}</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t("projectSettingsSearchPlaceholder")} /></label>
      </form>
      <label><span>{t("projectSettingsStatus")}</span>
        <DropdownSelect aria-label={t("projectSettingsStatus")} value={status} onChange={event => { setStatus(event.target.value as "active" | "archived"); setOffset(0); setSelected([]); }}>
          <option value="active">{t("projectSettingsStatusActive")}</option><option value="archived">{t("projectSettingsStatusArchived")}</option>
        </DropdownSelect>
      </label>
      <button className="action-button secondary" type="button" onClick={() => page.reload()}><RefreshCw size={16} />{t("refresh")}</button>
    </div>
    {page.data && !page.data.rerank_available ? <p className="field-note">{t("projectSettingsRerankSystemOff")}</p> : null}
    {archivedView ? <p className="field-note">{t("projectSettingsArchivedReadOnly")}</p> : null}
    {canChange ? <div className="project-settings-bulk" aria-live="polite">
      <strong>{format("projectSettingsSelected", { count: selected.length })}</strong>
      <button className="action-button secondary" type="button" disabled={!selected.length || busy} onClick={() => setDialog("models")}><Cpu size={15} />{t("projectSettingsSetModels")}</button>
      <button className="action-button secondary" type="button" disabled={!selected.length || busy} onClick={() => setDialog("put_member")}><UserPlus size={15} />{t("projectSettingsPutMember")}</button>
      <button className="action-button secondary" type="button" disabled={!selected.length || busy} onClick={() => setDialog("remove_member")}><UserMinus size={15} />{t("projectSettingsRemoveMember")}</button>
      <button className="action-button secondary" type="button" disabled={!selected.length || busy || !page.data?.rerank_available} onClick={() => void run({ action: "set_rerank", project_ids: selected, rerank_enabled: true })}><ListFilter size={15} />{t("projectSettingsRerankOn")}</button>
      <button className="action-button secondary" type="button" disabled={!selected.length || busy} onClick={() => void run({ action: "set_rerank", project_ids: selected, rerank_enabled: false })}>{t("projectSettingsRerankOff")}</button>
    </div> : null}
    {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}
    {page.status === "error" ? <FeedbackMessage tone="error">{operationalErrorMessage(page.error, t, format, "projectSettingsLoadFailed")}</FeedbackMessage> : null}
    {results ? <ProjectSettingsResults results={results.rows} names={names} onClose={() => setResults(null)} /> : null}
    {page.status !== "loading" && !rows.length ? <p className="field-note">{t("projectSettingsEmpty")}</p> : null}
    {rows.length ? <DataTable rows={rows} rowKey={row => row.id} wrapClassName="project-settings-table" columns={[
      ...(canChange ? [{ key: "select", headerLabel: t("projectSettingsSelectAll"), header: <input type="checkbox" aria-label={t("projectSettingsSelectAll")} checked={allSelected} onChange={event => setSelected(event.target.checked ? rows.map(row => row.id) : [])} />,
        cell: (row: ProjectSettingsItem) => <input type="checkbox" aria-label={format("projectSettingsSelectProject", { name: row.name })} checked={selected.includes(row.id)} onChange={event => setSelected(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} /> }] : []),
      { key: "name", header: t("projectSettingsProject"), rowHeader: true, cell: row => <strong>{row.name}</strong> },
      { key: "chat", header: t("labelChat"), cell: row => modelName(row.llm_model) },
      { key: "embedding", header: "Embedding", cell: row => modelName(row.embedding_model) },
      { key: "ocr", header: t("labelPdfRecognition"), cell: row => modelName(row.ocr_model) },
      { key: "owners", header: t("projectSettingsOwners"), cell: row => <>{row.owners.map(owner => owner.display_name).join("、") || "-"}<small>{format("projectSettingsMemberCount", { count: row.member_count })}</small></> },
      { key: "rerank", header: t("projectSettingsRerank"), className: "approval-administration-nowrap", cell: row => <StateBadge tone={row.rerank_enabled ? "green" : "gray"}>{t(row.rerank_enabled ? "projectRerankOn" : "projectRerankOff")}</StateBadge> },
      { key: "members", headerLabel: t("systemActionsColumn"), className: "approval-administration-nowrap", cell: row => <button className="action-button secondary" type="button" onClick={() => void openDetail(row)}><UsersRound size={15} />{t("projectSettingsMembers")}</button> },
    ]} /> : null}
    {page.data && page.data.total > PAGE_SIZE ? <div className="project-settings-pagination">
      <button className="icon-button" type="button" aria-label={t("systemPreviousPage")} disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE_SIZE)); setSelected([]); }}><ChevronLeft size={16} /></button>
      <span>{format("projectSettingsPage", { from: offset + 1, to: Math.min(offset + PAGE_SIZE, page.data.total), total: page.data.total })}</span>
      <button className="icon-button" type="button" aria-label={t("systemNextPage")} disabled={offset + PAGE_SIZE >= page.data.total} onClick={() => { setOffset(offset + PAGE_SIZE); setSelected([]); }}><ChevronRight size={16} /></button>
    </div> : null}
    {dialog === "models" ? <ModelsDialog apiFetch={apiFetch} count={selected.length} busy={busy} onClose={() => setDialog(null)} onSubmit={models => void run({ action: "set_models", project_ids: selected, ...models })} /> : null}
    {dialog === "put_member" || dialog === "remove_member" ? <MemberDialog apiFetch={apiFetch} mode={dialog} count={selected.length} busy={busy} onClose={() => setDialog(null)}
      onSubmit={(userId, role) => void run(dialog === "put_member" ? { action: "put_member", project_ids: selected, user_id: userId, role: role! } : { action: "remove_member", project_ids: selected, user_id: userId })} /> : null}
    {detail ? <MembersDialog project={detail} onClose={() => setDetail(null)} /> : null}
  </SettingsCard>;
}

export function ProjectSettingsResults({ results, names, onClose }: { results: ProjectSettingsResult[]; names: Map<string, string>; onClose: () => void }) {
  const { t, format } = useI18n();
  const failed = results.filter(row => row.status === "failed");
  const updated = results.filter(row => row.status === "updated").length;
  return <FeedbackMessage tone={failed.length ? "warning" : "success"} title={format("projectSettingsResultSummary", { updated, unchanged: results.length - updated - failed.length, failed: failed.length })}
    actions={<button className="action-button secondary" type="button" onClick={onClose}>{t("close")}</button>}>
    {failed.length ? <ul className="project-settings-failures">{failed.map(row => <li key={row.project_id}><strong>{names.get(row.project_id) ?? row.project_id}</strong>：{row.error_code && REASONS[row.error_code] ? t(REASONS[row.error_code]) : format("projectSettingsReasonOther", { code: row.error_code ?? "-" })}</li>)}</ul> : null}
  </FeedbackMessage>;
}

export function ModelsDialog({ apiFetch, count, busy, onClose, onSubmit }: { apiFetch: ApiFetch; count: number; busy: boolean; onClose: () => void; onSubmit: (models: { llm_model_id?: string; embedding_model_id?: string; ocr_model_id?: string }) => void }) {
  const { t, format } = useI18n();
  const [choice, setChoice] = useState<{ llm_model_id?: string; embedding_model_id?: string; ocr_model_id?: string }>({});
  const readModels = useCallback((signal: AbortSignal) => listModels(apiFetch, undefined, signal), [apiFetch]);
  const models = useReadResource<AIModelResponse[]>(readModels, "project-settings-models", true);
  const options = (type: string) => (models.data ?? []).filter(model => model.model_type === type && model.is_active);
  const fields: { key: keyof typeof choice; type: string; label: TranslationKey | "Embedding" }[] = [
    { key: "llm_model_id", type: "Chat", label: "labelChat" }, { key: "embedding_model_id", type: "Embedding", label: "Embedding" }, { key: "ocr_model_id", type: "OCR", label: "labelPdfRecognition" }];
  const chosen = Object.values(choice).some(Boolean);
  return <Modal aria-labelledby="project-settings-models-title" className="modal-panel modal-compact" onBackdropMouseDown={() => { if (!busy) onClose(); }} onEscape={() => { if (!busy) onClose(); }}>
    <div className="modal-header"><div><p className="eyebrow">{format("projectSettingsSelected", { count })}</p><h2 id="project-settings-models-title">{t("projectSettingsSetModels")}</h2></div>
      <button aria-label={t("close")} className="icon-button" disabled={busy} onClick={onClose} type="button"><X size={18} /></button></div>
    <form onSubmit={event => { event.preventDefault(); if (chosen) onSubmit(Object.fromEntries(Object.entries(choice).filter(([, value]) => value))); }}>
      <p className="field-note">{t("projectSettingsModelsHelp")}</p>
      {fields.map(field => <label className="field-stack" key={field.key}><span>{field.label === "Embedding" ? "Embedding" : t(field.label)}</span>
        <DropdownSelect disabled={busy || models.status === "loading"} value={choice[field.key] ?? ""} onChange={event => setChoice(current => ({ ...current, [field.key]: event.target.value || undefined }))}>
          <option value="">{t("projectSettingsKeepModel")}</option>{options(field.type).map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
        </DropdownSelect></label>)}
      {choice.embedding_model_id ? <FeedbackMessage tone="warning">{t("projectSettingsEmbeddingWarning")}</FeedbackMessage> : null}
      <div className="modal-actions"><button className="action-button secondary" disabled={busy} onClick={onClose} type="button">{t("cancel")}</button>
        <button className="action-button" disabled={busy || !chosen} type="submit">{busy ? t("loadingData") : t("projectSettingsApply")}</button></div>
    </form>
  </Modal>;
}

export function MemberDialog({ apiFetch, mode, count, busy, onClose, onSubmit }: { apiFetch: ApiFetch; mode: "put_member" | "remove_member"; count: number; busy: boolean; onClose: () => void; onSubmit: (userId: string, role?: string) => void }) {
  const { t, format } = useI18n();
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<string>("viewer");
  const [searching, setSearching] = useState(false);
  const adding = mode === "put_member";
  async function find() {
    if (!query.trim()) return;
    setSearching(true);
    try { setUsers((await listUsersPage(apiFetch, { q: query.trim(), limit: 20, isActive: true })).items); }
    catch { setUsers([]); }
    finally { setSearching(false); }
  }
  const title: TranslationKey = adding ? "projectSettingsPutMember" : "projectSettingsRemoveMember";
  return <Modal aria-labelledby="project-settings-member-title" className="modal-panel modal-compact" onBackdropMouseDown={() => { if (!busy) onClose(); }} onEscape={() => { if (!busy) onClose(); }}>
    <div className="modal-header"><div><p className="eyebrow">{format("projectSettingsSelected", { count })}</p><h2 id="project-settings-member-title">{t(title)}</h2></div>
      <button aria-label={t("close")} className="icon-button" disabled={busy} onClick={onClose} type="button"><X size={18} /></button></div>
    <form onSubmit={event => { event.preventDefault(); if (userId) onSubmit(userId, adding ? role : undefined); }}>
      <p className="field-note">{t(adding ? "projectSettingsPutMemberHelp" : "projectSettingsRemoveMemberHelp")}</p>
      <div className="project-settings-user-search">
        <label className="field-stack"><span>{t("projectsSearchUsers")}</span><input type="search" value={query} disabled={busy} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); void find(); } }} placeholder={t("projectsSearchUsersPlaceholder")} /></label>
        <button className="action-button secondary" type="button" disabled={busy || searching || !query.trim()} onClick={() => void find()}>{t("projectSettingsFindUser")}</button>
      </div>
      <label className="field-stack"><span>{t("projectSettingsUser")}</span>
        <DropdownSelect disabled={busy || !users.length} value={userId} onChange={event => setUserId(event.target.value)}>
          <option value="">{users.length ? t("projectSettingsChooseUser") : t("projectSettingsSearchFirst")}</option>
          {users.map(user => <option key={user.id} value={user.id}>{user.display_name}{user.email ? ` · ${user.email}` : ""}</option>)}
        </DropdownSelect></label>
      {adding ? <label className="field-stack"><span>{t("projectSettingsRole")}</span>
        <DropdownSelect disabled={busy} value={role} onChange={event => setRole(event.target.value)}>
          {ROLES.map(item => <option key={item} value={item}>{t(item === "owner" ? "projectRoleOwner" : item === "editor" ? "projectRoleEditor" : "projectRoleViewer")}</option>)}
        </DropdownSelect></label> : null}
      <div className="modal-actions"><button className="action-button secondary" disabled={busy} onClick={onClose} type="button">{t("cancel")}</button>
        <button className={`action-button${adding ? "" : " danger"}`} disabled={busy || !userId} type="submit">{busy ? t("loadingData") : t("projectSettingsApply")}</button></div>
    </form>
  </Modal>;
}

export function MembersDialog({ project, onClose }: { project: ProjectSettingsItem; onClose: () => void }) {
  const { t } = useI18n();
  const label = (role: string) => t(role === "owner" ? "projectRoleOwner" : role === "editor" ? "projectRoleEditor" : "projectRoleViewer");
  return <Modal aria-labelledby="project-settings-members-title" className="modal-panel modal-compact" onBackdropMouseDown={onClose} onEscape={onClose}>
    <div className="modal-header"><div><p className="eyebrow">{project.name}</p><h2 id="project-settings-members-title">{t("projectSettingsMembers")}</h2></div>
      <button aria-label={t("close")} className="icon-button" onClick={onClose} type="button"><X size={18} /></button></div>
    {project.members?.length ? <DataTable rows={project.members} rowKey={member => member.user_id} columns={[
      { key: "name", header: t("projectSettingsUser"), rowHeader: true, cell: member => <><strong>{member.display_name}</strong><small>{member.email ?? ""}</small></> },
      { key: "role", header: t("projectSettingsRole"), cell: member => label(member.role) },
    ]} /> : <p className="field-note">{t("projectSettingsNoMembers")}</p>}
  </Modal>;
}
