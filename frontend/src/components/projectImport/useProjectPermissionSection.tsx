"use client";

import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { useCallback, useState } from "react";
import { AlertTriangle, Clock3, ShieldCheck, Trash2, UserPlus, UserRoundCog, X } from "lucide-react";
import { ProjectMemberAutocomplete } from "@/components/ProjectMemberAutocomplete";
import { ProjectMemberRoleSelector } from "@/components/ProjectMemberRoleSelector";
import { getProject, listProjectMembers, removeProjectMember, replaceProjectMember, searchProjectMemberCandidates, type ApiError, type ProjectMemberCandidate, type ProjectMemberResponse } from "@/lib/api";
import { formatPersonName } from "@/lib/personName";
import { availableProjectMemberCandidates, projectMemberOwnerProtection } from "@/lib/projectPermissions";
import { useDebouncedProjectMemberCandidateSearch } from "@/lib/useDebouncedProjectMemberCandidateSearch";
import { projectMemberRoles, type ProjectMemberRole, projectImportErrorMessage } from "@/components/projectImport/importDocumentModel";
import type { ImportPageDeps } from "./pageDeps";

type ProjectPermissionStateDeps = Pick<ImportPageDeps, "apiFetch" | "canManageProjectPermissions" | "params" | "t">;
/** Page dependencies shared with the project permission actions. */
export type ProjectPermissionDeps = Pick<ImportPageDeps, "apiFetch" | "canManageProjectPermissions" | "currentUser" | "params" | "project" | "setProject" | "setProjectAccess">;

export type ProjectPermissionState = ReturnType<typeof useProjectPermissionState>;

/** Project member permission state (split from the project import page, OPT424-038). */
export function useProjectPermissionState(deps: ProjectPermissionStateDeps) {
  const { apiFetch, canManageProjectPermissions, params, t } = deps;
  const [permissionModalOpen, setPermissionModalOpen] = useState(false);
  const [projectMembers, setProjectMembers] = useState<ProjectMemberResponse[]>([]);
  const [permissionQuery, setPermissionQuery] = useState("");
  const [pendingPermissionUsers, setPendingPermissionUsers] = useState<ProjectMemberCandidate[]>([]);
  const [activePermissionRole, setActivePermissionRole] = useState<ProjectMemberRole>("owner");
  const [permissionLoading, setPermissionLoading] = useState(false);
  const [permissionError, setPermissionError] = useState<ApiError | Error | null>(null);
  const [permissionSavingUserId, setPermissionSavingUserId] = useState<string | null>(null);
  const [permissionRemovingUserId, setPermissionRemovingUserId] = useState<string | null>(null);
  const permissionRoleLabel = (role: ProjectMemberRole) => t(projectMemberRoles.find((item) => item.id === role)?.labelKey ?? "projectRoleViewer");
  const membersForActiveRole = projectMembers.filter((member) => member.roles.includes(activePermissionRole));
  const searchPermissionCandidates = useCallback(
    (query: string, signal: AbortSignal) => searchProjectMemberCandidates(apiFetch, params.id, query, signal),
    [apiFetch, params.id],
  );
  const permissionCandidateSearch = useDebouncedProjectMemberCandidateSearch({
    enabled: permissionModalOpen && canManageProjectPermissions,
    query: permissionQuery,
    search: searchPermissionCandidates,
  });
  const permissionUsers = permissionCandidateSearch.result?.items ?? [];
  const filteredPermissionUsers = availableProjectMemberCandidates(
    permissionUsers,
    projectMembers,
    new Set(pendingPermissionUsers.map((user) => user.id)),
  );
  const permissionSearchMessage = permissionCandidateSearch.phase === "waiting" || permissionCandidateSearch.phase === "loading"
    ? t("projectImportPermissionSearchLoading")
    : permissionCandidateSearch.phase === "error"
      ? t("projectImportPermissionSearchFailed")
      : permissionCandidateSearch.phase === "ready" && !filteredPermissionUsers.length
        ? permissionUsers.length
          ? t("projectImportPermissionSearchNoAdditionalRole")
          : (permissionCandidateSearch.result?.ineligible_match_count ?? 0) > 0
            ? t("projectImportPermissionSearchMissingAccess")
            : t("projectImportPermissionSearchNoResults")
        : "";
  return { permissionModalOpen, setPermissionModalOpen, projectMembers, setProjectMembers, permissionQuery, setPermissionQuery, pendingPermissionUsers, setPendingPermissionUsers, activePermissionRole, setActivePermissionRole, permissionLoading, setPermissionLoading, permissionError, setPermissionError, permissionSavingUserId, setPermissionSavingUserId, permissionRemovingUserId, setPermissionRemovingUserId, permissionRoleLabel, membersForActiveRole, searchPermissionCandidates, permissionCandidateSearch, permissionUsers, filteredPermissionUsers, permissionSearchMessage };
}

/** Project member permission actions, created each render once workspace dependencies exist. */
export function createProjectPermissionActions(state: ProjectPermissionState, deps: ProjectPermissionDeps) {
  const { setPermissionModalOpen, projectMembers, setProjectMembers, setPermissionQuery, pendingPermissionUsers, setPendingPermissionUsers, activePermissionRole, setActivePermissionRole, setPermissionLoading, setPermissionError, permissionSavingUserId, setPermissionSavingUserId, permissionRemovingUserId, setPermissionRemovingUserId } = state;

  async function loadProjectPermissions() {
    const { apiFetch, params, setProject, setProjectAccess } = deps;
    setPermissionLoading(true);
    setPermissionError(null);
    try {
      const [members, freshProject] = await Promise.all([listProjectMembers(apiFetch, params.id), getProject(apiFetch, params.id)]);
      setProjectMembers(members);
      setProject(freshProject);
      setProjectAccess("granted");
    } catch (error) {
      setPermissionError(error as ApiError | Error);
      if ((error as ApiError).status === 401 || (error as ApiError).status === 403) setProjectAccess("denied");
    } finally {
      setPermissionLoading(false);
    }
  }

  function openPermissionModal() {
    const { canManageProjectPermissions } = deps;
    if (!canManageProjectPermissions) return;
    setPermissionModalOpen(true);
    setPermissionQuery("");
    setPendingPermissionUsers([]);
    setActivePermissionRole("owner");
    void loadProjectPermissions();
  }

  async function saveProjectMemberRole(userId: string, role: ProjectMemberRole) {
    const { apiFetch, canManageProjectPermissions, currentUser, params, project, setProject } = deps;
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId) return;
    const member = projectMembers.find((row) => row.user_id === userId);
    if (member && projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id)) return;
    setPermissionSavingUserId(userId);
    setPermissionError(null);
    try {
      const members = await replaceProjectMember(apiFetch, params.id, userId, { roles: [role], lock_version: project.lock_version });
      const freshProject = await getProject(apiFetch, params.id);
      setProjectMembers(members);
      setProject(freshProject);
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionSavingUserId(null);
    }
  }

  function stagePermissionCandidate(user: ProjectMemberCandidate) {
    setPendingPermissionUsers((current) => current.some((item) => item.id === user.id) ? current : [...current, user]);
    setPermissionQuery("");
  }

  async function commitPendingPermissionCandidates() {
    const { apiFetch, canManageProjectPermissions, params, project, setProject } = deps;
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId || !pendingPermissionUsers.length) return;
    setPermissionSavingUserId("pending-members");
    setPermissionError(null);
    try {
      let currentProject = project;
      let currentMembers = projectMembers;
      for (const user of pendingPermissionUsers) {
        if (currentMembers.some((member) => member.user_id === user.id)) continue;
        currentMembers = await replaceProjectMember(apiFetch, params.id, user.id, { roles: [activePermissionRole], lock_version: currentProject.lock_version });
        currentProject = await getProject(apiFetch, params.id);
      }
      setProjectMembers(currentMembers);
      setProject(currentProject);
      setPendingPermissionUsers([]);
      setPermissionQuery("");
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionSavingUserId(null);
    }
  }

  async function removeProjectPermissionMember(userId: string) {
    const { apiFetch, canManageProjectPermissions, currentUser, params, project, setProject } = deps;
    if (!project || !canManageProjectPermissions || permissionSavingUserId || permissionRemovingUserId) return;
    const member = projectMembers.find((row) => row.user_id === userId);
    if (member && projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id)) return;
    setPermissionRemovingUserId(userId);
    setPermissionError(null);
    try {
      const updated = await removeProjectMember(apiFetch, params.id, userId, project.lock_version);
      const members = await listProjectMembers(apiFetch, params.id);
      setProjectMembers(members);
      setProject(updated);
    } catch (error) {
      setPermissionError(error as ApiError | Error);
    } finally {
      setPermissionRemovingUserId(null);
    }
  }

  return { loadProjectPermissions, openPermissionModal, saveProjectMemberRole, stagePermissionCandidate, commitPendingPermissionCandidates, removeProjectPermissionMember };
}

export type ProjectPermissionActions = ReturnType<typeof createProjectPermissionActions>;

/** Project member permission view: JSX moved verbatim from the project import page (OPT424-038). */
export function createProjectPermissionView(state: ProjectPermissionState, actions: ProjectPermissionActions, deps: Pick<ImportPageDeps, "canManageProjectPermissions" | "currentUser" | "format" | "locale" | "project" | "t">) {
  const { setPermissionModalOpen, projectMembers, permissionQuery, setPermissionQuery, pendingPermissionUsers, setPendingPermissionUsers, activePermissionRole, setActivePermissionRole, permissionLoading, permissionError, permissionSavingUserId, permissionRemovingUserId, permissionRoleLabel, membersForActiveRole, filteredPermissionUsers, permissionSearchMessage } = state;
  const { loadProjectPermissions, saveProjectMemberRole, stagePermissionCandidate, commitPendingPermissionCandidates, removeProjectPermissionMember } = actions;

  function renderProjectPermissionModal() {
    const { canManageProjectPermissions, currentUser, format, locale, project, t } = deps;
    return (
      (
      <Modal onEscape={() => setPermissionModalOpen(false)} aria-labelledby="project-permissions-title" className="modal-panel project-permission-modal">
          <div className="modal-header">
            <div className="modal-title-row">
              <span className="modal-title-icon"><UserRoundCog size={20} /></span>
              <div>
                <p className="eyebrow">{project?.name ?? t("projectImportFallbackProjectTitle")}</p>
                <h2 id="project-permissions-title">{t("projectImportPermissionManagement")}</h2>
              </div>
            </div>
            <button className="icon-button" onClick={() => setPermissionModalOpen(false)} type="button" aria-label={t("projectImportClosePermissionModal")}>
              <X size={18} />
            </button>
          </div>
          {permissionError ? <FeedbackMessage tone="error"><strong>{projectImportErrorMessage(permissionError, t, format)}</strong><button className="text-link" onClick={loadProjectPermissions} type="button">{t("retry")}</button></FeedbackMessage> : null}
          {permissionLoading ? <div className="empty-state compact" role="status"><Clock3 size={24} /><p>{t("loadingData")}</p></div> : (
            <div className="project-permission-body">
              <section className="create-section project-permission-section">
                <div className="create-section-title"><UserRoundCog size={18} /><h3>{t("projectsOwnersAndMembers")}</h3></div>
                {!canManageProjectPermissions ? <div className="permission-note locked"><AlertTriangle size={16} /> {t("projectImportPermissionOwnerOnly")}</div> : null}
                <div className="member-search">
                  <ProjectMemberAutocomplete
                    candidates={filteredPermissionUsers}
                    disabled={!canManageProjectPermissions || Boolean(permissionSavingUserId || permissionRemovingUserId)}
                    id="project-permission-user-search"
                    label={t("projectsSearchUsers")}
                    locale={locale}
                    onQueryChange={setPermissionQuery}
                    onSelect={stagePermissionCandidate}
                    placeholder={t("projectsSearchUsersPlaceholder")}
                    statusMessage={permissionSearchMessage}
                    value={permissionQuery}
                  />
                  <button className="action-button secondary" disabled={!canManageProjectPermissions || !pendingPermissionUsers.length || Boolean(permissionSavingUserId || permissionRemovingUserId)} onClick={() => { void commitPendingPermissionCandidates(); }} type="button"><UserPlus size={16} /> {t("projectsAddMember")}</button>
                  {pendingPermissionUsers.length ? (
                    <div className="project-permission-selected-users">
                      {pendingPermissionUsers.map((user) => (
                        <span className="project-permission-selected-user" key={user.id}>
                          {formatPersonName(user, locale)}
                          <button aria-label={t("projectImportRemovePendingMember")} onClick={() => setPendingPermissionUsers((current) => current.filter((item) => item.id !== user.id))} type="button">
                            <X size={13} />
                          </button>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div aria-label={t("projectsMemberRolesAria")} className="role-tabs" role="tablist">{projectMemberRoles.map((role) => <button aria-selected={activePermissionRole === role.id} className={activePermissionRole === role.id ? "role-tab active" : "role-tab"} key={role.id} onClick={() => { setPendingPermissionUsers([]); setActivePermissionRole(role.id); }} role="tab" type="button">{permissionRoleLabel(role.id)}<span>{projectMembers.filter((member) => member.roles.includes(role.id)).length}</span></button>)}</div>
                <div className="project-permission-member-list">
                  {membersForActiveRole.map((member) => {
                    const currentRole = member.roles.find((role): role is ProjectMemberRole => projectMemberRoles.some((item) => item.id === role));
                    if (!currentRole) return null;
                    const busy = permissionSavingUserId === member.user_id || permissionRemovingUserId === member.user_id;
                    const protection = projectMemberOwnerProtection(member, projectMembers, currentUser?.user_id);
                    const protectionId = protection ? `project-member-protection-${member.user_id}` : undefined;
                    return (
                      <article className={protection ? "project-permission-member protected" : "project-permission-member"} key={member.user_id}>
                        <div>
                          <strong>{formatPersonName(member, locale)}</strong>
                          <small>{member.email ?? member.user_id}</small>
                          {protection ? <span className="project-permission-protection-reason" id={protectionId}><ShieldCheck size={13} />{t(protection === "last_owner" ? "projectImportLastOwnerProtected" : "projectImportSelfOwnerProtected")}</span> : null}
                        </div>
                        <ProjectMemberRoleSelector
                          describedBy={protectionId}
                          disabled={!canManageProjectPermissions || busy || Boolean(protection)}
                          label={t("projectsMemberRolesAria")}
                          memberId={member.user_id}
                          onChange={(role) => { void saveProjectMemberRole(member.user_id, role); }}
                          options={projectMemberRoles.map((role) => ({ id: role.id, label: permissionRoleLabel(role.id) }))}
                          role={currentRole}
                        />
                        {protection ? null : <button className="icon-button danger" disabled={!canManageProjectPermissions || busy} onClick={() => { void removeProjectPermissionMember(member.user_id); }} title={t("projectImportRemoveMember")} type="button" aria-label={t("projectImportRemoveMember")}><Trash2 size={17} /></button>}
                      </article>
                    );
                  })}
                  {!membersForActiveRole.length ? <div className="empty-state compact">{t("projectImportNoMembersInRole")}</div> : null}
                </div>
                <p className="field-note">{t("projectImportPermissionHelp")}</p>
              </section>
            </div>
          )}
          <div className="modal-actions"><button className="action-button secondary" onClick={() => setPermissionModalOpen(false)} type="button">{t("close")}</button></div>
        </Modal>
    )
    );
  }

  return { renderProjectPermissionModal };
}
