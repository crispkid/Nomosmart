"use client";

import { useRef, useState, type Dispatch, type MutableRefObject, type ReactNode, type SetStateAction } from "react";
import { Ellipsis, Eye, Link2, LoaderCircle, LockKeyhole, Pencil, ShieldCheck, Trash2, Unlink, UsersRound } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { createRole, deleteRole, getRoleUsers, replacePermissions, replaceRoleUsers, setRoleExternalGroupMapping, updateRole, type ApiError, type ApiFetch, type ExternalGroupResponse, type listExternalGroupMappings, type RoleResponse, type RoleUsersResponse } from "@/lib/api";
import { identitySourceLabel } from "@/lib/identitySource";
import { roleMemberCounts, roleRow, type RoleRow, type UserRow } from "@/lib/systemManagement";
import { emptyPermissionState, permissionPayload, permissionStateFromResponse, type GroupMappingRow, type PermissionAction, type PermissionState, type RoleStatusFilter } from "./permissionHelpers";
import { StateBadge } from "./SystemUi";
import type { TranslationKey } from "@/lib/i18nClient";
import type { ModalState, SystemReadState } from "./modalState";
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
