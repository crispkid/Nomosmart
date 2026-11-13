"use client";

import { useState } from "react";
import { ChevronRight, RefreshCw, Save, Search } from "lucide-react";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackForm } from "@/components/FeedbackForm";
import { SettingsCard } from "../SettingsCard";
import { identitySourceLabel } from "@/lib/identitySource";
import { formatCount } from "@/lib/numberFormat";
import { EmptyInlineState, SectionHeader, StateBadge } from "./SystemUi";
import { updateUser, updateUserStatus, type ApiFetch, type UserSummary } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import { userRow, type UserRow } from "@/lib/systemManagement";
import type { ModalState } from "./modalState";
import type { WorkspaceViewDeps } from "./viewDeps";

/** Workspace dependencies shared with the user section. */
export type UserDeps = {
  apiFetch: ApiFetch;
  modal: ModalState | null;
  runModalMutation: <T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title?: TranslationKey) => Promise<void>;
};

export type UserState = ReturnType<typeof useUserState>;

/** User maintenance state (split from SystemManagementWorkspace, OPT424-038). */
export function useUserState() {
  const [liveUsers, setLiveUsers] = useState<UserRow[]>([]);
  const [userTableIds, setUserTableIds] = useState<string[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [userOverallTotal, setUserOverallTotal] = useState<number | null>(null);
  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(20);
  const [userQuery, setUserQuery] = useState("");
  const [userSourceFilter, setUserSourceFilter] = useState("all");
  return { liveUsers, setLiveUsers, userTableIds, setUserTableIds, userTotal, setUserTotal, userOverallTotal, setUserOverallTotal, userPage, setUserPage, userPageSize, setUserPageSize, userQuery, setUserQuery, userSourceFilter, setUserSourceFilter };
}

/** User maintenance actions, created each render once workspace dependencies exist. */
export function createUserActions(state: UserState, deps: UserDeps) {
  const { liveUsers, setLiveUsers, userTableIds, setUserTableIds, userTotal, setUserTotal, userOverallTotal, setUserOverallTotal, userPage, setUserPage, userPageSize, setUserPageSize, userQuery, setUserQuery, userSourceFilter, setUserSourceFilter } = state;

  function cacheUsers(rows: UserSummary[]) {
    setLiveUsers(current => {
      const map = new Map(current.map(row => [row.id, row]));
      rows.forEach(user => map.set(user.id, userRow(user)));
      return [...map.values()];
    });
  }

  async function submitUser(formData: FormData) {
    const { apiFetch, modal, runModalMutation } = deps;
    if (modal?.type !== "user") return;
    const payload: Parameters<typeof updateUser>[2] = {
      knowledge_owner: formData.get("knowledge_owner") === "on", system_notes: String(formData.get("system_notes") || "")
    };
    const baseline = modal.user.raw?.manager_delegate_user_id;
    if (baseline !== undefined && formData.has("manager_delegate_user_id")) {
      const selected = String(formData.get("manager_delegate_user_id") || "").trim() || null;
      if (selected !== baseline) payload.manager_delegate_user_id = selected;
    }
    await runModalMutation(() => updateUser(apiFetch, modal.user.id, payload), updated => { setLiveUsers(current => current.map(user => user.id === updated.id ? userRow(updated) : user)); }, "systemUserLocalFieldsSaved");
  }

  async function toggleUser(user: UserRow, accepted: () => void) {
    const { apiFetch } = deps;
    const next = user.status !== "active";
    const updated = await updateUserStatus(apiFetch, user.id, next); accepted();
    setLiveUsers((current) => current.map((item) => item.id === user.id ? { ...item, status: updated.is_active ? "active" : "inactive", raw: updated } : item));
  }

  return { cacheUsers, submitUser, toggleUser };
}

export type UserActions = ReturnType<typeof createUserActions>;

/** User view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createUserView(state: UserState, actions: UserActions, deps: Pick<WorkspaceViewDeps, "canEditUsers" | "closeModal" | "discardModal" | "filteredUsers" | "format" | "locale" | "localizedStatus" | "modal" | "modalBlocked" | "renderListPager" | "runIdentitySync" | "sectionReads" | "sectionReady" | "setModal" | "submitting" | "t" | "userRowName">) {
  const { liveUsers, userTotal, userPage, setUserPage, userPageSize, setUserPageSize, userQuery, setUserQuery, userSourceFilter, setUserSourceFilter } = state;
  const { submitUser, toggleUser } = actions;

  function renderUserPanel() {
    const { canEditUsers, filteredUsers, format, locale, localizedStatus, renderListPager, runIdentitySync, sectionReads, sectionReady, setModal, t, userRowName } = deps;
    return (
      <SettingsCard panel="users">
      <SectionHeader action={<button className="action-button secondary" disabled={!canEditUsers} onClick={runIdentitySync} type="button"><RefreshCw size={16} />{t("systemSyncNow")}</button>} description={t("systemUserManagementDescription")} title={t("systemUserManagementTitle")} />
      <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchUsers")} maxLength={100} onChange={(event) => { setUserQuery(event.target.value); setUserPage(1); }} placeholder={t("systemSearchUsersPlaceholder")} value={userQuery} /></label><DropdownSelect aria-label={t("systemFilterIdentitySource")} onChange={(event) => { setUserSourceFilter(event.target.value); setUserPage(1); }} value={userSourceFilter}><option value="all">{t("systemAllIdentitySources")}</option>{Array.from(new Set(["ldap", "ad", "local", ...liveUsers.map(user => user.source), ...(userSourceFilter === "all" ? [] : [userSourceFilter])])).map((source) => <option key={source} value={source}>{identitySourceLabel(source, t)}</option>)}</DropdownSelect><span>{format("systemUserCount", { filtered: sectionReads.users?.received ? formatCount(filteredUsers.length, locale) : t("systemReadCountUnknown"), total: sectionReads.users?.received ? formatCount(userTotal, locale) : t("systemReadCountUnknown") })}</span></div>
      {filteredUsers.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemUser")}</th><th>{t("systemDepartment")}</th><th>{t("systemIdentitySourceColumn")}</th><th>{t("systemRoleColumn")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{filteredUsers.map((user) => <tr key={user.id}><td><strong>{userRowName(user)}</strong><small>{user.email}</small></td><td>{user.department}</td><td>{identitySourceLabel(user.source, t)}</td><td>{user.roles}</td><td><StateBadge tone={user.status === "active" ? "green" : "gray"}>{localizedStatus(user.status)}</StateBadge></td><td><div className="system-row-actions"><button aria-label={format("systemViewUser", { name: userRowName(user) })} className="icon-text-button" onClick={() => setModal({ type: "user", user })} type="button">{t("systemView")} <ChevronRight size={15} /></button><button className="icon-text-button" disabled={!canEditUsers} onClick={() => setModal({ type: "confirm", title: `${user.status === "active" ? t("systemDisable") : t("systemEnable")}${t("systemUser")}`, message: format("systemConfirmToggleUser", { action: user.status === "active" ? t("systemDisable") : t("systemEnable"), name: userRowName(user) }), actionLabel: user.status === "active" ? t("systemDisable") : t("systemEnable"), target: { kind: "user", id: user.id, expected: { field: "is_active", value: user.status !== "active" } }, run: accepted => toggleUser(user, accepted) })} type="button">{user.status === "active" ? t("systemDisable") : t("systemEnable")}</button></div></td></tr>)}</tbody></table></div> : sectionReady("users") ? <EmptyInlineState /> : null}
      {renderListPager("users", userPage, userPageSize, userTotal, () => setUserPage(page => page - 1), userPage * userPageSize < userTotal ? () => setUserPage(page => page + 1) : null, size => { setUserPageSize(size); setUserPage(1); })}
    </SettingsCard>
    );
  }

  function renderUserForm(modal: Extract<ModalState, { type: "user" }>) {
    const { canEditUsers, closeModal, discardModal, localizedStatus, modalBlocked, submitting, t, userRowName } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitUser(new FormData(event.currentTarget)); }}>
      <div className="system-detail-grid"><div><small>{t("systemName")}</small><strong>{userRowName(modal.user)}</strong></div><div><small>{t("labelEmail")}</small><strong>{modal.user.email}</strong></div><div><small>{t("systemSourceColumn")}</small><strong>{identitySourceLabel(modal.user.source, t)}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.user.status)}</strong></div></div>
      <label className="identity-toggle"><input defaultChecked={Boolean(modal.user.raw?.knowledge_owner)} name="knowledge_owner" type="checkbox" /><span>{t("labelKnowledgeOwner")}</span></label>
      <label><span>{t("systemManagerDelegateOptional")}</span><input defaultValue={modal.user.raw?.manager_delegate_user_id ?? ""} disabled={modal.user.raw?.manager_delegate_user_id === undefined} name="manager_delegate_user_id" placeholder="UUID" />{modal.user.raw?.manager_delegate_user_id === undefined ? <small>{t("systemManagerDelegateUnavailable")}</small> : null}</label>
      <label><span>{t("labelSystemNotes")}</span><textarea defaultValue={modal.user.raw?.system_notes ?? ""} name="system_notes" rows={4} /></label>
      <footer><button className="action-button secondary" onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={!canEditUsers || submitting} type="submit"><Save size={16} />{t("save")}</button></footer>
    </FeedbackForm>
    );
  }

  return { renderUserPanel, renderUserForm };
}
