"use client";

import { useRef, useState, type Dispatch, type MutableRefObject, type ReactNode, type SetStateAction } from "react";
import { Check, DatabaseZap, Ellipsis, Eye, Info, Link2, LoaderCircle, LockKeyhole, Pencil, Plus, Save, Search, ShieldCheck, Trash2, Unlink, UserRoundCog, UsersRound, X } from "lucide-react";
import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackForm } from "@/components/FeedbackForm";
import { SettingsCard } from "../SettingsCard";
import { formatCount } from "@/lib/numberFormat";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { createRole, deleteRole, getRoleUsers, replacePermissions, replaceRoleUsers, setRoleExternalGroupMapping, updateRole, type ApiError, type ApiFetch, type ExternalGroupResponse, type listExternalGroupMappings, type RoleResponse, type RoleUsersResponse } from "@/lib/api";
import { identitySourceLabel } from "@/lib/identitySource";
import { roleMemberCounts, roleRow, type RoleRow, type UserRow } from "@/lib/systemManagement";
import { emptyPermissionState, permissionActionEnabled, permissionMenuRows, permissionPayload, permissionStateFromResponse, type GroupMappingRow, type PermissionAction, type PermissionState, type RoleStatusFilter } from "./permissionHelpers";
import { EmptyInlineState, SectionHeader, StateBadge } from "./SystemUi";
import type { TranslationKey } from "@/lib/i18nClient";
import type { ModalState, SystemReadState } from "./modalState";
import type { WorkspaceViewDeps } from "./viewDeps";
import type { QuickMutationTarget } from "./useModelSection";

/** Workspace dependencies shared with the role section. */
export type RoleDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  format: (key: TranslationKey, params: Record<string, string | number>) => string;
  modal: ModalState | null;
  setModal: (next: SetStateAction<ModalState | null>) => void;
  setModalError: Dispatch<SetStateAction<string>>;
  setSystemError: Dispatch<SetStateAction<ApiError | Error | null>>;
  canDeleteRoles: boolean;
  canEditPermissions: boolean;
  canEditRoles: boolean;
  quickBlocked: boolean;
  selectedRoleReadOnly: boolean;
  breakGlassRoleUserIds: Set<string>;
  draftRoleUserIds: Set<string>;
  externalRoleUserIds: Set<string>;
  originalManualRoleUserIds: Set<string>;
  groupRows: MutableRefObject<ExternalGroupResponse[]>;
  mappingRows: MutableRefObject<Awaited<ReturnType<typeof listExternalGroupMappings>>>;
  roleNames: MutableRefObject<Map<string, string>>;
  systemReadStates: MutableRefObject<Record<string, SystemReadState>>;
  systemReadScope: string;
  readSystemSection: <T>(section: string, read: () => Promise<T>, apply: (value: T) => void, outerCurrent?: () => boolean) => Promise<boolean>;
  reloadSystemSection: (section: string, current?: () => boolean) => Promise<boolean>;
  renderSectionReadNotice: (section: string, title?: string, announce?: boolean) => ReactNode;
  runModalMutation: <T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title?: TranslationKey) => Promise<void>;
  runQuickMutation: (target: QuickMutationTarget, write: () => Promise<unknown>, refresh: (current: () => boolean) => Promise<void>) => Promise<void>;
  sectionReady: (section: string) => boolean;
};

export type RoleState = ReturnType<typeof useRoleState>;

/** Role, membership, mapping and permission management state (split from SystemManagementWorkspace, OPT424-038). */
export function useRoleState() {
  const [selectedRole, setSelectedRole] = useState("");
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>({});
  const [permissionSaved, setPermissionSaved] = useState(true);
  const [liveRoles, setLiveRoles] = useState<RoleRow[]>([]);
  const [liveGroupMappings, setLiveGroupMappings] = useState<GroupMappingRow[]>([]);
  const [externalGroups, setExternalGroups] = useState<ExternalGroupResponse[]>([]);
  const [roleTableIds, setRoleTableIds] = useState<string[]>([]);
  const [roleTotal, setRoleTotal] = useState(0);
  const [roleOverallTotal, setRoleOverallTotal] = useState<number | null>(null);
  const [rolePage, setRolePage] = useState(1);
  const [rolePageSize, setRolePageSize] = useState(20);
  const [memberOffset, setMemberOffset] = useState(0);
  const [memberTotal, setMemberTotal] = useState(0);
  const [memberCandidateIds, setMemberCandidateIds] = useState<string[]>([]);
  const [roleUsersReadback, setRoleUsersReadback] = useState<RoleUsersResponse | null>(null);
  const [roleUsers, setRoleUsers] = useState<RoleUsersResponse | null>(null);
  const [roleUserDraftIds, setRoleUserDraftIds] = useState<string[]>([]);
  const [roleUserSearch, setRoleUserSearch] = useState("");
  const [rolesView, setRolesView] = useState<"local" | "ldap">("local");
  const [roleQuery, setRoleQuery] = useState("");
  const [roleStatusFilter, setRoleStatusFilter] = useState<RoleStatusFilter>("all");
  const [roleActionId, setRoleActionId] = useState<string | null>(null);
  const [roleDeleteConfirmation, setRoleDeleteConfirmation] = useState("");
  const [mappingGroupDraft, setMappingGroupDraft] = useState("");
  const roleMenuTriggerRef = useRef<HTMLElement | null>(null);
  return { selectedRole, setSelectedRole, permissions, setPermissions, permissionSaved, setPermissionSaved, liveRoles, setLiveRoles, liveGroupMappings, setLiveGroupMappings, externalGroups, setExternalGroups, roleTableIds, setRoleTableIds, roleTotal, setRoleTotal, roleOverallTotal, setRoleOverallTotal, rolePage, setRolePage, rolePageSize, setRolePageSize, memberOffset, setMemberOffset, memberTotal, setMemberTotal, memberCandidateIds, setMemberCandidateIds, roleUsersReadback, setRoleUsersReadback, roleUsers, setRoleUsers, roleUserDraftIds, setRoleUserDraftIds, roleUserSearch, setRoleUserSearch, rolesView, setRolesView, roleQuery, setRoleQuery, roleStatusFilter, setRoleStatusFilter, roleActionId, setRoleActionId, roleDeleteConfirmation, setRoleDeleteConfirmation, mappingGroupDraft, setMappingGroupDraft, roleMenuTriggerRef };
}

/** Role, membership, mapping and permission management actions, created each render once workspace dependencies exist. */
export function createRoleActions(state: RoleState, deps: RoleDeps) {
  const { selectedRole, setSelectedRole, permissions, setPermissions, permissionSaved, setPermissionSaved, liveRoles, setLiveRoles, liveGroupMappings, setLiveGroupMappings, externalGroups, setExternalGroups, roleTableIds, setRoleTableIds, roleTotal, setRoleTotal, roleOverallTotal, setRoleOverallTotal, rolePage, setRolePage, rolePageSize, setRolePageSize, memberOffset, setMemberOffset, memberTotal, setMemberTotal, memberCandidateIds, setMemberCandidateIds, roleUsersReadback, setRoleUsersReadback, roleUsers, setRoleUsers, roleUserDraftIds, setRoleUserDraftIds, roleUserSearch, setRoleUserSearch, rolesView, setRolesView, roleQuery, setRoleQuery, roleStatusFilter, setRoleStatusFilter, roleActionId, setRoleActionId, roleDeleteConfirmation, setRoleDeleteConfirmation, mappingGroupDraft, setMappingGroupDraft, roleMenuTriggerRef } = state;

  function cacheRoles(rows: RoleResponse[]) {
    const { roleNames } = deps;
    rows.forEach(role => roleNames.current.set(role.id, role.name));
    setLiveRoles(current => {
      const map = new Map(current.map(row => [row.id, row]));
      rows.forEach(role => map.set(role.id, roleRow(role, map.get(role.id))));
      return [...map.values()];
    });
  }

  function applyMemberSnapshot(roleId: string, response: RoleUsersResponse) {
    setLiveRoles(rows => rows.map(row => row.id === roleId ? { ...row, ...roleMemberCounts(response), lockVersion: response.lock_version } : row));
  }

  function updateMappingProjection() {
    const { groupRows, mappingRows, roleNames, systemReadScope, systemReadStates } = deps;
    const known = systemReadStates.current.mappings?.scope === systemReadScope && systemReadStates.current.mappings?.phase === "ready";
    setLiveRoles(current => current.map(role => {
      const mapping = mappingRows.current.find(row => row.role_id === role.id);
      return { ...role, groups: known ? (mapping ? 1 : 0) : null, mappingGroupId: known ? mapping?.external_group_id ?? null : role.mappingGroupId };
    }));
    const groups = new Map(groupRows.current.map(group => [group.id, group]));
    setLiveGroupMappings(mappingRows.current.map(mapping => ({ groupId: mapping.external_group_id, roleId: mapping.role_id, group: groups.get(mapping.external_group_id)?.path || groups.get(mapping.external_group_id)?.group_name || mapping.external_group_id, source: groups.get(mapping.external_group_id)?.identity_origin || "keycloak_local", role: roleNames.current.get(mapping.role_id) ?? mapping.role_id, members: groups.get(mapping.external_group_id)?.member_count ?? null })));
  }

  async function readRoleMembers(role: Pick<RoleRow, "id">, current: () => boolean = () => true) {
    const { apiFetch, readSystemSection } = deps;
    setLiveRoles(rows => rows.map(row => row.id === role.id ? { ...row, members: null, manualMembers: null, ldapMembers: null, breakGlassMembers: null } : row));
    return readSystemSection(`members:${role.id}`, () => getRoleUsers(apiFetch, role.id), response => {
      setLiveRoles(rows => rows.map(row => row.id === role.id ? { ...row, ...roleMemberCounts(response) } : row));
    }, current);
  }

  function togglePermission(key: string, action: PermissionAction) {
    const { canEditPermissions, selectedRoleReadOnly } = deps;
    if (!canEditPermissions || selectedRoleReadOnly) return;
    setPermissions((current) => ({
      ...current,
      [selectedRole]: {
        ...(current[selectedRole] ?? emptyPermissionState()),
        [key]: { ...((current[selectedRole] ?? emptyPermissionState())[key]), [action]: !((current[selectedRole] ?? emptyPermissionState())[key][action]) }
      }
    }));
    setPermissionSaved(false);
  }

  async function savePermissions() {
    const { apiFetch, setSystemError } = deps;
    const role = liveRoles.find((item) => item.id === selectedRole);
    if (!role || role.isActive === false || !permissions[selectedRole]) return;
    try {
      const response = await replacePermissions(apiFetch, selectedRole, permissionPayload(role, permissions[selectedRole]));
      setPermissions((current) => ({ ...current, [selectedRole]: permissionStateFromResponse(response) }));
      setLiveRoles((current) => current.map((item) => item.id === selectedRole ? { ...item, lockVersion: response.lock_version } : item));
      setPermissionSaved(true);
      setSystemError(null);
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }

  async function refreshRolesAndMappings(current: () => boolean = () => true) {
    const { reloadSystemSection } = deps;
    const results = await Promise.all(["roles", "groups", "mappings"].map(section => reloadSystemSection(section, current)));
    if (current() && results.some(value => !value)) throw new Error("System read could not be confirmed");
  }

  async function submitRole(formData: FormData) {
    const { apiFetch, modal, runModalMutation } = deps;
    const name = modal?.type === "role" && modal.role?.isSystem ? modal.role.name : String(formData.get("name") || "").trim();
    const description = String(formData.get("description") || "").trim() || null;
    await runModalMutation(() => modal?.type === "role" && modal.role ? updateRole(apiFetch, modal.role.id, { lock_version: modal.role.lockVersion, name, description }) : createRole(apiFetch, { name, description }), (_result, current) => refreshRolesAndMappings(current), "systemRoleDataUpdated");
  }

  async function openRoleUsers(role: RoleRow) {
    const { apiFetch, setModal, setModalError } = deps;
    setModalError("");
    const response = await getRoleUsers(apiFetch, role.id);
    setRoleUsers(response); setRoleUsersReadback(null); setMemberOffset(0); setMemberCandidateIds([]);
    setRoleUserDraftIds(response.users.filter((row) => row.source === "manual").map((row) => row.user_id));
    setRoleUserSearch("");
    setModal({ type: "role-users", role });
  }

  function toggleRoleUserDraft(userId: string, checked: boolean) {
    setRoleUserDraftIds((current) => checked ? [...new Set([...current, userId])] : current.filter((id) => id !== userId));
  }

  function roleUserStatusLabels(user: UserRow) {
    const { breakGlassRoleUserIds, draftRoleUserIds, externalRoleUserIds, originalManualRoleUserIds, t } = deps;
    const labels: Array<{ label: string; tone: "green" | "gold" | "coral" | "gray" }> = [];
    if (externalRoleUserIds.has(user.id)) labels.push({ label: t("systemRoleUserLdapMember"), tone: "gold" });
    if (breakGlassRoleUserIds.has(user.id)) labels.push({ label: t("systemRoleUserBreakGlassMember"), tone: "coral" });
    if (draftRoleUserIds.has(user.id) && !originalManualRoleUserIds.has(user.id)) labels.push({ label: t("systemRoleUserPendingAdd"), tone: "green" });
    else if (!draftRoleUserIds.has(user.id) && originalManualRoleUserIds.has(user.id)) labels.push({ label: t("systemRoleUserPendingRemove"), tone: "coral" });
    else if (originalManualRoleUserIds.has(user.id)) labels.push({ label: t("systemRoleUserManualMember"), tone: "gray" });
    if (!labels.length) labels.push({ label: t("systemRoleUserAvailable"), tone: "gray" });
    return labels;
  }

  function roleUserIdentityLine(user: UserRow) {
    const { format, t } = deps;
    const parts = [
      user.email,
      user.raw?.employee_id ? format("systemEmployeeIdValue", { id: user.raw.employee_id }) : null,
      identitySourceLabel(user.source, t)
    ].filter(Boolean);
    return parts.join(" · ");
  }

  async function saveRoleUsers() {
    const { apiFetch, modal, runModalMutation } = deps;
    if (modal?.type !== "role-users" || modal.role.isActive === false || !roleUsers) return;
    await runModalMutation(() => replaceRoleUsers(apiFetch, modal.role.id, { lock_version: roleUsers.lock_version, user_ids: roleUserDraftIds }), async (response, current) => {
      setRoleUsers(response); setRoleUserDraftIds(response.users.filter(row => row.source === "manual").map(row => row.user_id));
      await refreshRolesAndMappings(current);
    }, "systemManualRoleUsersSaved");
  }

  function openRoleMapping(role: RoleRow) {
    const { setModal, setModalError } = deps;
    setMappingGroupDraft(role.mappingGroupId ?? "");
    setModalError("");
    setModal({ type: "mapping", role });
  }

  async function saveRoleMapping() {
    const { apiFetch, modal, runModalMutation } = deps;
    if (modal?.type !== "mapping" || modal.role.isActive === false) return;
    await runModalMutation(() => setRoleExternalGroupMapping(apiFetch, modal.role.id, { external_group_id: mappingGroupDraft || null, lock_version: modal.role.lockVersion }), (_result, current) => refreshRolesAndMappings(current), "systemMappingsSaved");
  }

  async function changeRoleLifecycle(role: RoleRow, isActive: boolean, accepted: () => void, current: () => boolean) {
    const { apiFetch, setSystemError } = deps;
    setRoleActionId(role.id);
    setSystemError(null);
    try {
      await updateRole(apiFetch, role.id, { lock_version: role.lockVersion, is_active: isActive }); accepted();
      await refreshRolesAndMappings(current);
    } finally {
      setRoleActionId(null);
    }
  }

  function openRoleDelete(role: RoleRow, trigger: HTMLElement) {
    const { setModal, setModalError } = deps;
    roleMenuTriggerRef.current = trigger.closest("details")?.querySelector("summary") ?? trigger;
    setRoleDeleteConfirmation("");
    setModalError("");
    setModal({ type: "role-delete", role });
  }

  async function submitRoleDelete(role: RoleRow) {
    const { apiFetch, runModalMutation } = deps;
    await runModalMutation(() => deleteRole(apiFetch, role.id, role.lockVersion, roleDeleteConfirmation), (_result, current) => refreshRolesAndMappings(current), "feedbackRoleDeleted");
  }

  function renderLocalRoleCard(role: RoleRow) {
    const { apiFetch, canDeleteRoles, canEditRoles, format, quickBlocked, renderSectionReadNotice, runQuickMutation, sectionReady, setModal, setSystemError, t } = deps;
    const isActive = role.isActive !== false;
    const isBusy = roleActionId === role.id;
    const mappedGroup = externalGroups.find((group) => group.id === role.mappingGroupId);
    const mappedGroupName = !sectionReady("mappings") || !sectionReady("groups") ? t("systemReadCountUnknown") : mappedGroup?.path || mappedGroup?.group_name || t("systemNoMapping");
    const mappingIsEditable = isActive && canEditRoles;

    return (
      <article aria-busy={isBusy} className={`system-role-card${isActive ? "" : " inactive"}`} key={role.id}>
        <header className="system-role-card-header">
          <span className="role-icon"><ShieldCheck size={18} /></span>
          <div className="system-role-card-title">
            <h3>{role.name}</h3>
            {role.isSystem ? <div className="system-role-card-badges"><StateBadge tone="gold">{t("systemProtectedDefaultRole")}</StateBadge></div> : null}
          </div>
          <div className="system-role-card-controls">
            <label className="system-role-lifecycle">
              <span>{isActive ? t("systemEnabled") : t("systemDisabled")}</span>
              <button
                aria-checked={isActive}
                aria-label={format("systemRoleLifecycleControl", { name: role.name, status: isActive ? t("systemEnabled") : t("systemDisabled") })}
                className="system-role-switch"
                disabled={role.isSystem || !canEditRoles || quickBlocked || isBusy}
                onClick={() => {
                  if (isActive) {
                    setModal({
                      type: "confirm",
                      title: t("systemDisableRoleTitle"),
                      message: format("systemDisableRoleHelp", { name: role.name }),
                      actionLabel: t("systemDisable"),
                      successTitle: "feedbackRoleDisabled", target: { kind: "role", id: role.id, expected: { field: "is_active", value: false } }, run: (accepted, current) => changeRoleLifecycle(role, false, accepted, current)
                    });
                  } else {
                    void runQuickMutation({ kind: "role", id: role.id, field: "is_active", value: true }, () => updateRole(apiFetch, role.id, { lock_version: role.lockVersion, is_active: true }), refreshRolesAndMappings);
                  }
                }}
                role="switch"
                title={role.isSystem ? t("systemRoleProtectedLifecycle") : undefined}
                type="button"
              >
                <span />
              </button>
            </label>
            {!role.isSystem && canDeleteRoles ? <details className="system-role-menu">
              <summary aria-label={format("systemRoleMoreActions", { name: role.name })}><Ellipsis size={18} /></summary>
              <div role="menu">
                <button className="destructive" onClick={(event) => openRoleDelete(role, event.currentTarget)} role="menuitem" type="button"><Trash2 size={15} />{t("systemDelete")}</button>
              </div>
            </details> : null}
          </div>
        </header>

        <p className="system-role-description">{role.description || t("systemRoleNoDescription")}</p>

        <dl className="system-role-facts">
          <div>
            <dt><Link2 size={15} />{t("systemMappedLdapGroup")}</dt>
            <dd title={mappedGroupName}>{mappedGroupName}</dd>
          </div>
          <div>
            <dt><UsersRound size={15} />{t("systemRoleMemberSources")}</dt>
            <dd><span>{format("systemRoleManualMembers", { count: role.manualMembers ?? t("systemReadCountUnknown") })}</span><span>{format("systemRoleLdapMembers", { count: role.ldapMembers ?? t("systemReadCountUnknown") })}</span>{role.breakGlassMembers ? <span>{format("systemRoleBreakGlassMembers", { count: role.breakGlassMembers ?? t("systemReadCountUnknown") })}</span> : null}</dd>
          </div>
        </dl>

        {role.members === null ? renderSectionReadNotice(`members:${role.id}`, t("systemRoleMembersUnknown"), false) ?? <FeedbackMessage tone="info" announce={false}>{t("systemRoleMembersUnknown")}</FeedbackMessage> : null}
        {!isActive ? <div className="system-role-readonly-note"><LockKeyhole size={14} /><span>{t("systemRoleReadOnlyHelp")}</span></div> : null}

        <footer className="system-card-actions">
          <button className="icon-text-button" disabled={isActive && !canEditRoles} onClick={() => setModal({ type: "role", role })} type="button">{isActive ? <Pencil size={15} /> : <Eye size={15} />}{isActive ? t("systemEdit") : t("systemRoleDetails")}</button>
          <button className="icon-text-button" onClick={() => { void openRoleUsers(role).catch((caught) => setSystemError(caught as ApiError | Error)); }} type="button"><UsersRound size={15} />{t("systemRoleUsers")}</button>
          <button className="icon-text-button" disabled={!sectionReady("mappings") || !sectionReady("groups")} onClick={() => openRoleMapping(role)} type="button">{role.mappingGroupId ? <Unlink size={15} /> : <Link2 size={15} />}{mappingIsEditable ? (role.mappingGroupId ? t("systemChangeOrRemoveMapping") : t("systemSetMapping")) : t("systemViewMapping")}</button>
        </footer>

        {isBusy ? <div className="system-role-card-loading" role="status"><LoaderCircle className="spin" size={18} /><span>{t("systemRoleUpdating")}</span></div> : null}
      </article>
    );
  }

  return { cacheRoles, applyMemberSnapshot, updateMappingProjection, readRoleMembers, togglePermission, savePermissions, refreshRolesAndMappings, submitRole, openRoleUsers, toggleRoleUserDraft, roleUserStatusLabels, roleUserIdentityLine, saveRoleUsers, openRoleMapping, saveRoleMapping, changeRoleLifecycle, openRoleDelete, submitRoleDelete, renderLocalRoleCard };
}

export type RoleActions = ReturnType<typeof createRoleActions>;

/** Role and permission view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createRoleView(state: RoleState, actions: RoleActions, deps: Pick<WorkspaceViewDeps, "activeRoleUserCandidates" | "availableMappingGroups" | "breakGlassRoleUserIds" | "canCreateRoles" | "canEditPermissions" | "canEditRoles" | "closeModal" | "discardModal" | "draftRoleUserIds" | "externalRoleUserIds" | "filteredLocalRoles" | "filteredRoleUserCandidates" | "format" | "ldapGroups" | "liveUsers" | "locale" | "modal" | "modalBlocked" | "originalManualRoleUserIds" | "pendingAddUsers" | "pendingRemoveUsers" | "renderListPager" | "renderSectionReadNotice" | "requestSettingsLeave" | "sectionReady" | "selectedRoleReadOnly" | "setModal" | "submitting" | "t" | "userRowName">) {
  const { selectedRole, setSelectedRole, permissions, permissionSaved, setPermissionSaved, liveRoles, liveGroupMappings, externalGroups, roleTotal, roleOverallTotal, rolePage, setRolePage, rolePageSize, setRolePageSize, setMemberOffset, memberTotal, memberCandidateIds, roleUsersReadback, roleUserDraftIds, roleUserSearch, setRoleUserSearch, rolesView, setRolesView, roleQuery, setRoleQuery, roleStatusFilter, setRoleStatusFilter, roleDeleteConfirmation, setRoleDeleteConfirmation, mappingGroupDraft, setMappingGroupDraft } = state;
  const { togglePermission, savePermissions, submitRole, toggleRoleUserDraft, roleUserStatusLabels, roleUserIdentityLine, saveRoleUsers, saveRoleMapping, submitRoleDelete, renderLocalRoleCard } = actions;

  function renderRolePanel() {
    const { canCreateRoles, filteredLocalRoles, format, ldapGroups, locale, renderListPager, sectionReady, setModal, t } = deps;
    return (
      <SettingsCard panel="roles">
      <SectionHeader action={rolesView === "local" ? <button className="action-button" disabled={!canCreateRoles || !sectionReady("roles")} onClick={() => setModal({ type: "role" })} type="button"><UserRoundCog size={16} />{t("systemAddRole")}</button> : undefined} description={t("systemRolesDescription")} title={t("systemRolesTitle")} />
      <div aria-label={t("systemRoleTypeViews")} className="system-role-type-tabs" role="tablist">
        <button aria-selected={rolesView === "local"} className={rolesView === "local" ? "active" : ""} onClick={() => setRolesView("local")} role="tab" type="button"><ShieldCheck size={16} />{t("systemLocalRoles")}<span>{roleOverallTotal === null ? t("systemReadCountUnknown") : formatCount(roleOverallTotal, locale)}</span></button>
        <button aria-selected={rolesView === "ldap"} className={rolesView === "ldap" ? "active" : ""} onClick={() => setRolesView("ldap")} role="tab" type="button"><DatabaseZap size={16} />{t("systemLdapGroups")}<span>{ldapGroups.length}</span></button>
      </div>
      {rolesView === "local" ? <>
        <div className="system-role-toolbar">
          <label><Search size={16} /><input aria-label={t("systemSearchRoles")} maxLength={100} onChange={(event) => { setRoleQuery(event.target.value); setRolePage(1); }} placeholder={t("systemSearchRolesPlaceholder")} value={roleQuery} /></label>
          <div aria-label={t("systemRoleStatusFilter")} className="system-role-status-filter" role="group">
            {(["all", "enabled", "disabled"] as RoleStatusFilter[]).map((status) => <button aria-pressed={roleStatusFilter === status} className={roleStatusFilter === status ? "active" : ""} key={status} onClick={() => setRoleStatusFilter(status)} type="button">{status === "all" ? t("systemRoleFilterAll") : status === "enabled" ? t("systemEnabled") : t("systemDisabled")}</button>)}
          </div>
          <span aria-live="polite">{format("systemRoleResultCount", { filtered: formatCount(filteredLocalRoles.length, locale), total: formatCount(roleTotal, locale) })}</span>
        </div>
        {renderListPager("roles", rolePage, rolePageSize, roleTotal, () => setRolePage(page => page - 1), rolePage * rolePageSize < roleTotal ? () => setRolePage(page => page + 1) : null, size => { setRolePageSize(size); setRolePage(1); })}
        {filteredLocalRoles.length ? <div className="system-role-grid">{filteredLocalRoles.map(renderLocalRoleCard)}</div> : sectionReady("roles") ? <EmptyInlineState>{liveRoles.length ? t("systemNoMatchingRoles") : t("systemNoLocalRoles")}</EmptyInlineState> : null}
      </> : null}
      {rolesView === "ldap" ? <div className="system-ldap-groups"><div className="system-subsection-title"><div><h3><DatabaseZap size={18} />{t("systemLdapGroups")}</h3><p>{t("systemExternalGroupMappingsDescription")}</p></div></div>{ldapGroups.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemLdapGroup")}</th><th>{t("systemLdapPath")}</th><th>{t("systemMembersColumn")}</th><th>{t("systemNomoSmartRole")}</th><th>{t("systemStatusColumn")}</th></tr></thead><tbody>{ldapGroups.map((group) => { const mapping = liveGroupMappings.find((item) => item.groupId === group.id); return <tr key={group.id}><td><strong>{group.group_name}</strong><small>{t("systemLdapReadOnly")}</small></td><td>{group.path}</td><td>{group.member_count}</td><td>{mapping?.role ?? t("systemNoMapping")}</td><td><StateBadge tone={group.is_active ? "green" : "gray"}>{group.is_active ? t("systemSynced") : t("systemDisabled")}</StateBadge></td></tr>; })}</tbody></table></div> : <EmptyInlineState />}</div> : null}
    </SettingsCard>
    );
  }

  function renderPermissionPanel() {
    const { canEditPermissions, filteredLocalRoles, format, renderListPager, requestSettingsLeave, sectionReady, selectedRoleReadOnly, t } = deps;
    return (
      <SettingsCard panel="permissions">
      <SectionHeader action={<div className="system-save-state"><span>{permissionSaved ? <><Check size={15} />{t("systemSaved")}</> : t("systemUnsavedChanges")}</span><button className="action-button" disabled={!canEditPermissions || selectedRoleReadOnly || !sectionReady("roles") || !permissions[selectedRole]} onClick={savePermissions} title={!canEditPermissions ? t("apiForbidden") : selectedRoleReadOnly ? t("systemRoleReadOnly") : undefined} type="button"><Save size={16} />{t("systemSavePermissions")}</button></div>} description={t("systemPermissionsDescription")} title={t("systemPermissions")} />
      <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchRoles")} maxLength={100} onChange={event => { setRoleQuery(event.target.value); setRolePage(1); }} value={roleQuery} /></label></div>
      {renderListPager("roles", rolePage, rolePageSize, roleTotal, () => setRolePage(page => page - 1), rolePage * rolePageSize < roleTotal ? () => setRolePage(page => page + 1) : null, size => { setRolePageSize(size); setRolePage(1); })}
      <div className="role-selector" aria-label={t("systemSelectRole")}>{filteredLocalRoles.map((role) => <button aria-pressed={selectedRole === role.id} className={`${selectedRole === role.id ? "active" : ""}${role.isActive === false ? " inactive" : ""}`} key={role.id} onClick={() => requestSettingsLeave(() => { setSelectedRole(role.id); setPermissionSaved(true); })} type="button"><span>{role.name}</span><small>{format("systemRoleSelectorSummary", { members: role.members ?? t("systemReadCountUnknown"), groups: role.groups ?? t("systemReadCountUnknown") })} · {role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</small></button>)}</div>
      {selectedRoleReadOnly ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRolePermissionsReadOnlyHelp")}</p></div></FeedbackMessage> : null}
      {liveRoles.length ? <div className="permission-matrix-wrap"><table className="permission-matrix-table"><thead><tr><th>{t("systemMenuPermission")}</th><th>{t("permissionActionView")}</th><th>{t("permissionActionCreate")}</th><th>{t("permissionActionEdit")}</th><th>{t("permissionActionDelete")}</th><th>{t("permissionActionExecute")}</th></tr></thead><tbody>{permissionMenuRows.map((row) => { const state = permissions[selectedRole]?.[row.key] ?? emptyPermissionState()[row.key]; return <tr key={row.key}><td><strong>{t(row.labelKey as TranslationKey)}</strong><small>{t(row.descriptionKey as TranslationKey)}</small></td>{(["view", "create", "edit", "delete", "execute"] as PermissionAction[]).map((action) => { const enabled = permissionActionEnabled(row, action); return <td key={action}>{!enabled ? <span aria-label={t("settingsNotApplicable")}>—</span> : <input aria-label={`${liveRoles.find((role) => role.id === selectedRole)?.name ?? t("systemRoleColumn")} ${t(row.labelKey as TranslationKey)} ${t(`permissionAction${action.charAt(0).toUpperCase()}${action.slice(1)}` as TranslationKey)}`} checked={enabled && state[action]} disabled={!canEditPermissions || selectedRoleReadOnly || !enabled || !sectionReady("roles") || !permissions[selectedRole]} onChange={() => togglePermission(row.key, action)} type="checkbox" />}</td>; })}</tr>; })}</tbody></table></div> : <EmptyInlineState />}
    </SettingsCard>
    );
  }

  function renderRoleForm(modal: Extract<ModalState, { type: "role" }>) {
    const { canCreateRoles, canEditRoles, closeModal, discardModal, modalBlocked, submitting, t } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitRole(new FormData(event.currentTarget)); }}>
      <label><span>{t("systemRoleName")}</span><input defaultValue={modal.role?.name ?? ""} disabled={modal.role?.isSystem || modal.role?.isActive === false} name="name" required /></label>
      <label><span>{t("systemDescription")}</span><textarea defaultValue={modal.role?.description ?? ""} disabled={modal.role?.isActive === false} name="description" rows={3} /></label>
      {modal.role?.isSystem ? <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemRoleProtection")}</strong><p>{t("systemRoleProtectionHelp")}</p></div></div> : null}
      {modal.role?.isActive === false ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleReadOnlyHelp")}</p></div></FeedbackMessage> : null}
      <footer><button className="action-button secondary" onClick={closeModal} type="button">{modal.role?.isActive === false ? t("close") : t("cancel")}</button>{modal.role?.isActive === false ? null : <button className="action-button" disabled={submitting || (!modal.role && !canCreateRoles) || (Boolean(modal.role) && !canEditRoles)} type="submit"><Save size={16} />{t("save")}</button>}</footer>
    </FeedbackForm>
    );
  }

  function renderRoleUsersForm(modal: Extract<ModalState, { type: "role-users" }>) {
    const { activeRoleUserCandidates, breakGlassRoleUserIds, canEditRoles, closeModal, discardModal, draftRoleUserIds, externalRoleUserIds, filteredRoleUserCandidates, format, liveUsers, locale, modalBlocked, originalManualRoleUserIds, pendingAddUsers, pendingRemoveUsers, renderSectionReadNotice, sectionReady, submitting, t, userRowName } = deps;
    return (
      <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form role-user-editor" onSubmit={(event) => { event.preventDefault(); void saveRoleUsers(); }}>
      <p className="system-modal-help">{t("systemManualRoleUsersHelp")}</p>
      {modal.role.isActive === false ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleMembersReadOnlyHelp")}</p></div></FeedbackMessage> : null}
      <div className="role-user-search-row">
        <label><Search size={16} /><input aria-label={t("systemRoleUserSearch")} autoFocus maxLength={100} onChange={(event) => { setRoleUserSearch(event.target.value); setMemberOffset(0); }} placeholder={t("systemRoleUserSearchPlaceholder")} value={roleUserSearch} /></label>
        <span>{format("systemRoleUserSearchResultCount", { filtered: filteredRoleUserCandidates.length, total: activeRoleUserCandidates.length })}</span>
      </div>
      <section aria-label={t("systemRoleUserDraftSummary")} className="role-user-draft-summary">
        <div className="role-user-summary-metrics">
          <span><strong>{roleUserDraftIds.length}</strong><small>{t("systemRoleUserManualDraftCount")}</small></span>
          <span><strong>{externalRoleUserIds.size}</strong><small>{t("systemRoleUserExternalCount")}</small></span>
          <span><strong>{breakGlassRoleUserIds.size}</strong><small>{t("systemRoleUserBreakGlassCount")}</small></span>
          <span><strong>{pendingAddUsers.length}</strong><small>{t("systemRoleUserPendingAddCountShort")}</small></span>
          <span><strong>{pendingRemoveUsers.length}</strong><small>{t("systemRoleUserPendingRemoveCountShort")}</small></span>
        </div>
        {pendingAddUsers.length || pendingRemoveUsers.length ? <div className="role-user-draft-groups">
          <div>
            <h3><Plus size={15} />{format("systemRoleUserPendingAddCount", { count: pendingAddUsers.length })}</h3>
            {pendingAddUsers.length ? <div className="role-user-chip-list">{pendingAddUsers.map((user) => <span key={user.id}>{userRowName(user)}</span>)}</div> : <p>{t("systemRoleUserNoPendingAdds")}</p>}
          </div>
          <div>
            <h3><X size={15} />{format("systemRoleUserPendingRemoveCount", { count: pendingRemoveUsers.length })}</h3>
            {pendingRemoveUsers.length ? <div className="role-user-chip-list remove">{pendingRemoveUsers.map((user) => <span key={user.id}>{userRowName(user)}</span>)}</div> : <p>{t("systemRoleUserNoPendingRemoves")}</p>}
          </div>
        </div> : <p className="role-user-no-draft">{t("systemRoleUserNoDraftChanges")}</p>}
      </section>
      {filteredRoleUserCandidates.length ? <div aria-label={t("systemRoleUserSearchResults")} className="role-user-picker-list">
        {renderSectionReadNotice("memberCandidates")}
        {roleUsersReadback ? <FeedbackMessage tone="info" title={t("adminCurrentMembers")}><p>{format("adminMemberReadback", { count: formatCount(new Set(roleUsersReadback.users.map(user => user.user_id)).size, locale), version: formatCount(roleUsersReadback.lock_version, locale) })}</p><ul className="system-readback-members">{roleUsersReadback.users.map(member => { const user = liveUsers.find(row => row.id === member.user_id); return <li key={`${member.user_id}:${member.source}`}><span>{user ? userRowName(user) : member.user_id}</span><StateBadge>{t(member.source === "manual" ? "systemRoleUserManualMember" : member.source === "external_sync" ? "systemRoleUserLdapMember" : member.source === "break_glass" ? "systemRoleUserBreakGlassMember" : "adminMemberSourceUnknown")}</StateBadge></li>; })}</ul><small>{t("adminDraftBaselineHelp")}</small></FeedbackMessage> : null}
        {filteredRoleUserCandidates.map((user) => {
          const isExternal = externalRoleUserIds.has(user.id);
          const isBreakGlass = breakGlassRoleUserIds.has(user.id);
          const isRetained = isExternal || isBreakGlass;
          const isManualDraftMember = draftRoleUserIds.has(user.id);
          const checked = isManualDraftMember || isRetained;
          const statuses = roleUserStatusLabels(user);
          const rowClass = [
            "role-user-picker-row",
            isExternal ? "external-retained" : "",
            isBreakGlass ? "break-glass-retained" : "",
            isManualDraftMember && !originalManualRoleUserIds.has(user.id) ? "pending-add" : "",
            !isManualDraftMember && originalManualRoleUserIds.has(user.id) ? "pending-remove" : ""
          ].filter(Boolean).join(" ");
          return <label className={rowClass} key={user.id}><input checked={checked} disabled={!canEditRoles || modal.role.isActive === false || submitting || isRetained} name="user_ids" onChange={(event) => toggleRoleUserDraft(user.id, event.target.checked)} type="checkbox" value={user.id} /><span><strong>{userRowName(user)}</strong><small>{roleUserIdentityLine(user)}</small></span><div className="role-user-source-badges">{statuses.map((status) => <StateBadge key={status.label} tone={status.tone}>{status.label}</StateBadge>)}</div></label>;
        })}
      </div> : <EmptyInlineState>{t("systemRoleUserNoSearchResults")}</EmptyInlineState>}
      <div className="system-security-note"><ShieldCheck size={17} /><div><strong>{t("systemExternalSyncMembers")}</strong><p>{format("systemExternalSyncMembersRetained", { count: externalRoleUserIds.size, breakGlass: breakGlassRoleUserIds.size })}</p></div></div>
      {memberCandidateIds.length < memberTotal ? <button className="action-button secondary" disabled={!sectionReady("memberCandidates")} onClick={() => setMemberOffset(offset => offset + 20)} type="button">{t("adminLoadMore")}</button> : null}
      <footer><button className="action-button secondary" onClick={closeModal} type="button">{modal.role.isActive === false ? t("close") : t("cancel")}</button>{modal.role.isActive === false ? null : <button className="action-button" disabled={!canEditRoles || submitting} type="submit"><Save size={16} />{t("systemSaveUsers")}</button>}</footer>
    </FeedbackForm>
    );
  }

  function renderRoleMappingForm(modal: Extract<ModalState, { type: "mapping" }>) {
    const { availableMappingGroups, canEditRoles, closeModal, format, submitting, t } = deps;
    return (
      <div className="system-crud-form">
      <p className="system-modal-help">{format("systemRoleMappingHelp", { role: modal.role.name })}</p>
      {modal.role.isActive === false ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleMappingReadOnlyHelp")}</p></div></FeedbackMessage> : null}
      <div className="system-mapping-editor"><label><span>{t("systemLdapGroup")}<small>{t("systemOneToOneMappingHelp")}</small></span><DropdownSelect autoFocus disabled={modal.role.isActive === false || !canEditRoles} onChange={(event) => setMappingGroupDraft(event.target.value)} value={mappingGroupDraft}><option value="">{t("systemNoMapping")}</option>{availableMappingGroups.map((group) => <option key={group.id} value={group.id}>{group.path || group.group_name} · {format("systemMemberCount", { count: group.member_count })}</option>)}</DropdownSelect></label></div>
      <div className="system-security-note"><Info size={17} /><div><strong>{t("systemMappingImmediateTitle")}</strong><p>{t("systemMappingImmediateHelp")}</p></div></div>
      <footer><button className="action-button secondary" onClick={closeModal} type="button">{modal.role.isActive === false || !canEditRoles ? t("close") : t("cancel")}</button>{modal.role.isActive === false || !canEditRoles ? null : <button className="action-button" disabled={submitting} onClick={saveRoleMapping} type="button"><Save size={16} />{t("systemSaveMappings")}</button>}</footer>
    </div>
    );
  }

  function renderRoleDeleteForm(modal: Extract<ModalState, { type: "role-delete" }>) {
    const { closeModal, format, modalBlocked, submitting, t } = deps;
    return (
      <div className="system-crud-form role-delete-content">
      <FeedbackMessage tone="warning"><div><strong>{t("systemDeleteRoleWarningTitle")}</strong><p>{t("systemDeleteRoleWarningHelp")}</p></div></FeedbackMessage>
      <div className="system-detail-grid"><div><small>{t("systemRoleColumn")}</small><strong>{modal.role.name}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{modal.role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</strong></div><div><small>{t("systemMappedLdapGroup")}</small><strong>{externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.path || externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.group_name || t("systemNoMapping")}</strong></div><div><small>{t("systemMembersColumn")}</small><strong>{modal.role.members ?? t("systemReadCountUnknown")}</strong></div></div>
      <ul className="role-delete-impact"><li>{t("systemDeleteRoleImpactHidden")}</li><li>{t("systemDeleteRoleImpactMapping")}</li><li>{t("systemDeleteRoleImpactHistory")}</li></ul>
      <label><span>{format("systemDeleteRoleConfirmationLabel", { name: modal.role.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setRoleDeleteConfirmation(event.target.value)} placeholder={modal.role.name} value={roleDeleteConfirmation} /><small>{t("systemDeleteRoleConfirmationHelp")}</small></label>
      <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked || roleDeleteConfirmation !== modal.role.name} onClick={() => { void submitRoleDelete(modal.role); }} type="button"><Trash2 size={16} />{t("systemDeleteRolePermanently")}</button></footer>
    </div>
    );
  }

  return { renderRolePanel, renderPermissionPanel, renderRoleForm, renderRoleUsersForm, renderRoleMappingForm, renderRoleDeleteForm };
}
