"use client";

import { DropdownSelect } from "@/components/DropdownSelect";
import SystemParameterSettings from "./SystemParameterSettings";
import { SectionHeader, StateBadge, operationStatusLabel } from "./system/SystemUi";
import { SystemStatusPanel } from "./system/SystemStatusPanel";
import { modalScope, type ModalState, type ModelRow, type PromptRow, type SystemReadState } from "./system/modalState";
import { createApiKeyActions, createApiKeyView, useApiKeyState } from "./system/useApiKeySection";
import { createModelActions, createModelView, useModelState } from "./system/useModelSection";
import { createPromptActions, createPromptView, usePromptState } from "./system/usePromptSection";
import { createRoleActions, createRoleView, useRoleState } from "./system/useRoleSection";
import { createUserActions, createUserView, useUserState } from "./system/useUserSection";
import { createIdentityActions, createIdentityView, useIdentityState } from "./system/useIdentitySection";
import { permissionStateFromResponse } from "./system/permissionHelpers";
import { modelRow } from "./system/modelHelpers";
import { createOutcomeQueries } from "./system/useOutcomeQueries";
import { useModalFocus } from "./useModalFocus";
import { SettingsNavigation } from "./system/SettingsNavigation";
import { ApiKeyOneTimeDialog } from "./system/ApiKeyOneTimeDialog";
import { useSystemDialogFocus } from "./system/useSystemDialogFocus";
import { useGuardedLinkNavigation } from "./system/useGuardedLinkNavigation";
import { apiBaseUrl } from "@/lib/oidc";

import { useOperationGuard } from "./useOperationGuard";
import { FeedbackConfirm } from "./FeedbackConfirm";
import { useFeedback } from "./FeedbackProvider";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { formatCount } from "@/lib/numberFormat";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Activity, ChevronRight, KeyRound, LockKeyhole, MessageSquareText, RefreshCw, Search, Settings2, Trash2, X } from "lucide-react";
import { getBreakGlassStatus, getPermissions, getSystemStatus, listSystemPrompts, listExternalGroupMappings, listExternalGroups, listModels, listModelsPage, listUsersPage, listRolesPage, listProjectsPage, listIntegrationClientsPage, type ApiError, type ExternalGroupResponse, type OperationsStatusResponse, type ProjectResponse, type RoleResponse, listIdentitySyncRuns } from "@/lib/api";
import { ForbiddenState } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { type UserRow } from "@/lib/systemManagement";
import { Pagination } from "@/components/Pagination";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";
import { settingsSections, settingsPositionUrl, legacySettingsPositions, type SettingsPosition, type SystemTabId } from "@/lib/systemRouteState";

type TabId = SystemTabId;

type SystemManagementWorkspaceProps = { initialTab?: SystemTabId; initialPosition?: SettingsPosition };

export default function SystemManagementWorkspace({
  initialTab = "users", initialPosition = legacySettingsPositions[initialTab]
}: SystemManagementWorkspaceProps) {
  const { locale, t, format, localize } = useI18n();
  const { apiFetch, can, currentUser, operationGuards } = useAuth();
  const [position, setPosition] = useState<SettingsPosition>(initialPosition);
  const activeSection = position.section;
  const activeTab: TabId = activeSection === "people" ? "users" : activeSection === "ai" ? "models" : activeSection === "general" || activeSection === "documents" ? "parameters" : activeSection;
  const [parameterDirty, setParameterDirty] = useState(false);
  const identityState = useIdentityState();
  const { identityDirty, setIdentityDirty, setSyncRuns, setBreakGlassStatus } = identityState;
  const [settingsLeave, setSettingsLeave] = useState<(() => void) | null>(null);
  const leaveFocus = useRef<HTMLElement | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [settingsSearch, setSettingsSearch] = useState("");
  const navigationRef = useModalFocus(narrow && navOpen && !settingsLeave, () => setNavOpen(false));
  const leaveDialogRef = useModalFocus(Boolean(settingsLeave), () => setSettingsLeave(null));
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(query.matches); update();
    query.addEventListener("change", update); return () => query.removeEventListener("change", update);
  }, []);

  const roleState = useRoleState();
  const { selectedRole, setSelectedRole, setPermissions, permissionSaved, setPermissionSaved, liveRoles, setLiveRoles, setLiveGroupMappings, externalGroups, setExternalGroups, roleTableIds, setRoleTableIds, setRoleTotal, setRoleOverallTotal, rolePage, setRolePage, rolePageSize, memberOffset, setMemberOffset, setMemberTotal, memberCandidateIds, setMemberCandidateIds, setRoleUsersReadback, roleUsers, roleUserDraftIds, roleUserSearch, roleQuery, roleStatusFilter, roleMenuTriggerRef } = roleState;
  const userState = useUserState();
  const { liveUsers, setLiveUsers, userTableIds, setUserTableIds, setUserTotal, setUserOverallTotal, userPage, setUserPage, userPageSize, userQuery, userSourceFilter } = userState;
  const [liveModels, setLiveModels] = useState<ModelRow[]>([]);
  const modelState = useModelState();
  const { setModelTableRows, modelTableTotal, setModelTableTotal, setModelTableReceived, modelTablePage, setModelTablePage, modelTablePageSize, modelTableType, setModelTableLoading, setModelTableError } = modelState;
  const promptState = usePromptState();
  const { systemPrompts, setSystemPrompts, selectedPromptId, setSelectedPromptId, promptDraft, setPromptDraft, setPromptDraftSourceVersion, setPromptModelDraft, promptSaving, promptEditorOpen, setPromptEditorOpen, promptEditorPrompt, promptBaseline, setPromptBaseline, promptLeave, setPromptLeave, promptDialogRef, promptFocusRef } = promptState;
  const [liveProjects, setLiveProjects] = useState<ProjectResponse[]>([]);
  const apiKeyState = useApiKeyState();
  const { setIntegrationClients, apiKeyProjectDraft, apiKeyScopeDrafts, apiKeyOneTime, setApiKeyOneTime, clientQuery, clientCursors, setClientCursors, clientPageSize } = apiKeyState;
  const apiKeyDialogRef = useRef<HTMLElement>(null);

  const [systemStatus, setSystemStatus] = useState<OperationsStatusResponse | null>(null);
  const [liveReady, setLiveReady] = useState(false);
  const [loadedSystemScope, setLoadedSystemScope] = useState("");
  const [sectionReads, setSectionReads] = useState<Record<string, SystemReadState>>({});
  const [systemLoading, setSystemLoading] = useState(true);
  const [systemError, setSystemError] = useState<ApiError | Error | null>(null);
  const [quickError, setQuickError] = useState<ApiError | Error | null>(null);
  const [quickQueryFailed, setQuickQueryFailed] = useState(false);
  const { notify } = useFeedback();
  const [modal, setModalState] = useState<ModalState | null>(null);
  const userActions = createUserActions(userState, { apiFetch, modal, runModalMutation });
  const { cacheUsers } = userActions;
  const [dirtyModal, setDirtyModal] = useState<ModalState | null>(null);
  const [discardModal, setDiscardModal] = useState<ModalState | null>(null);
  const systemDialogRef = useSystemDialogFocus({ activeTab, apiKeyDialogRef, apiKeyOneTimeOpen: Boolean(apiKeyOneTime), modal, navigationRef, promptEditorOpen });
  const [modalError, setModalError] = useState("");
  const { guard: modalGuard, state: modalOperation, blocked: modalBlocked } = useOperationGuard(`${currentUser?.user_id}:${JSON.stringify(currentUser?.permissions ?? [])}:${modalScope(modal)}:${can("Menu", "SystemManagement", "view")}`, operationGuards);
  const { guard: promptGuard, state: promptOperation, blocked: promptBlocked } = useOperationGuard(`${currentUser?.user_id}:prompts:${selectedPromptId}:${can("Menu", "SystemManagement", "edit")}`, operationGuards);
  const { guard: quickGuard, state: quickOperation, blocked: quickBlocked } = useOperationGuard(`${currentUser?.user_id}:quick:${JSON.stringify(currentUser?.permissions ?? [])}`, operationGuards);
  const modalFeedbackError = modalError || (modalOperation.phase === "unknown" ? t("feedbackResultUnknown") : modalOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : "");
  const quickTarget = useRef<{ kind: "model" | "role"; id: string; field: "is_active" | "is_default"; value: boolean } | null>(null);
  const [modalQueryMessage, setModalQueryMessage] = useState("");
  const [modalReadback, setModalReadback] = useState("");
  const modalSuccess = useRef<TranslationKey>("feedbackSaved");
  const modalEventId = useRef<string>("");
  const modalReceiptId = useRef<string | null>(null);
  const modalMutationScope = useRef<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [clientNextCursor, setClientNextCursor] = useState<string | null>(null);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectOffset, setProjectOffset] = useState(0);
  const [projectTotal, setProjectTotal] = useState(0);
  const [projectCandidateIds, setProjectCandidateIds] = useState<string[]>([]);
  const canViewSystemManagement = can("Menu", "SystemManagement", "view");
  const canCreateSystemManagement = can("Menu", "SystemManagement", "create");
  const canEditSystemManagement = can("Menu", "SystemManagement", "edit");
  const canDeleteSystemManagement = can("Menu", "SystemManagement", "delete");
  const canEditPermissions = canEditSystemManagement;

  const canEditUsers = canEditSystemManagement;
  const canEditRoles = canEditSystemManagement;
  const canCreateRoles = canCreateSystemManagement;
  const canDeleteRoles = canDeleteSystemManagement;
  const canEditModels = canEditSystemManagement;
  const canCreateModels = canCreateSystemManagement;
  const canDeleteModels = canDeleteSystemManagement;
  const errorMessage = useCallback((error: ApiError | Error | null) => operationalErrorMessage(error, t, format), [format, t]);

  const modelTableRequestRef = useRef(0);
  const selectedRoleRecord = liveRoles.find((role) => role.id === selectedRole);
  const selectedRoleLockVersion = selectedRoleRecord?.lockVersion;
  const selectedRoleReadOnly = selectedRoleRecord?.isActive === false;
  const selectedRoleReady = selectedRoleLockVersion !== undefined;

  const localizedStatus = (status: string) => {
    if (status === "active") return t("systemEnabled");
    if (status === "inactive") return t("systemDisabled");
    return status;
  };
  const localizedOperationStatus = (status: string) => operationStatusLabel(status, t);

  const activeEmbeddingModels = liveModels.filter((model) => model.type === "Embedding" && model.status === "active");

  const systemReadScope = `${currentUser?.user_id}:${JSON.stringify(currentUser?.permissions ?? [])}`;
  const systemReadScopeRef = useRef<string | null>(systemReadScope);
  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const apiKeyActions = createApiKeyActions(apiKeyState, { apiFetch, t, format, modal, setModal, setModalError, setModalQueryMessage, systemReadScope, readScopeNow: () => systemReadScopeRef.current, cacheProjects, readSystemSection, reloadSystemSection, runModalMutation, sectionReady });
  const systemReadEpoch = useRef({ version: 0 });
  const systemReadVersions = useRef<Record<string, number>>({});
  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const promptActions = createPromptActions(promptState, { apiFetch, canEditModels, errorMessage, format, liveModels, localize, promptBlocked, promptGuard, promptOperation, reloadSystemSection, setReadState, systemReadScope, systemReadVersions, t });
  const { requestPromptLeave, renderPromptFeedback, handlePromptDialogKey, renderPromptEditor } = promptActions;
  const systemReadStates = useRef<Record<string, SystemReadState>>({});
  const mappingRows = useRef<Awaited<ReturnType<typeof listExternalGroupMappings>>>([]);
  const groupRows = useRef<ExternalGroupResponse[]>([]);
  const roleNames = useRef(new Map<string, string>());
  const draftStates = useRef({ prompts: false });
  useLayoutEffect(() => {
    const epoch = systemReadEpoch.current;
    systemReadScopeRef.current = systemReadScope; epoch.version++;
    systemReadStates.current = {}; mappingRows.current = []; groupRows.current = []; roleNames.current = new Map();

    return () => { systemReadScopeRef.current = null; epoch.version++; };
  }, [systemReadScope]);
  useLayoutEffect(() => {
    draftStates.current = { prompts: promptEditorOpen || promptDraft !== promptBaseline };
  }, [promptEditorOpen, promptDraft, promptBaseline]);

  function sectionReady(section: string) { return sectionReads[section]?.scope === systemReadScope && sectionReads[section]?.phase === "ready"; }
  function setReadState(section: string, state: SystemReadState) {
    systemReadStates.current[section] = state;
    setSectionReads(current => ({ ...current, [section]: state }));
  }
  async function readSystemSection<T>(section: string, read: () => Promise<T>, apply: (value: T) => void, outerCurrent: () => boolean = () => true) {
    const scope = systemReadScope;
    const epoch = systemReadEpoch.current.version;
    const generation = (systemReadVersions.current[section] ?? 0) + 1;
    systemReadVersions.current[section] = generation;
    const current = () => systemReadEpoch.current.version === epoch && systemReadScopeRef.current === scope && systemReadVersions.current[section] === generation && outerCurrent();
    const previous = systemReadStates.current[section];
    const received = previous?.scope === scope && previous.received;
    setReadState(section, { scope, phase: "loading", received: Boolean(received) });
    try {
      const value = await read();
      if (!current()) return false;
      apply(value);
      setReadState(section, { scope, phase: "ready", received: true });
      return true;
    } catch (caught) {
      if (!current()) return false;
      const error = caught as ApiError | Error;
      setReadState(section, { scope, phase: "status" in error && error.status === 403 ? "forbidden" : "error", received: Boolean(received), error });
      return false;
    }
  }
  function cacheProjects(rows: ProjectResponse[]) { setLiveProjects(current => [...new Map([...current, ...rows].map(row => [row.id, row])).values()]); }
  async function reloadSystemSection(section: string, current: () => boolean = () => true): Promise<boolean> {
    switch (section) {
      case "users": return readSystemSection(section, () => listUsersPage(apiFetch, { q: userQuery, authSource: userSourceFilter === "all" ? undefined : userSourceFilter, offset: (userPage - 1) * userPageSize, limit: userPageSize }), page => {
        cacheUsers(page.items); setUserTableIds(page.items.map(row => row.id)); setUserTotal(page.total);
        if (!userQuery.trim() && userSourceFilter === "all") setUserOverallTotal(page.total);
        const last = Math.max(1, Math.ceil(page.total / userPageSize)); if (userPage > last) setUserPage(last);
      }, current);
      case "roles": {
        const generation = (systemReadVersions.current.roles ?? 0) + 1;
        const valid = () => current() && systemReadVersions.current.roles === generation && systemReadScopeRef.current === systemReadScope;
        let loadedRows: RoleResponse[] | undefined;
        const success = await readSystemSection(section, () => listRolesPage(apiFetch, { q: roleQuery, isActive: roleStatusFilter === "all" ? undefined : roleStatusFilter === "enabled", offset: (rolePage - 1) * rolePageSize, limit: rolePageSize }), page => {
          loadedRows = page.items; cacheRoles(page.items); setRoleTableIds(page.items.map(row => row.id)); setRoleTotal(page.total);
          if (!roleQuery.trim() && roleStatusFilter === "all") setRoleOverallTotal(page.total);
          setSelectedRole(selected => selected || page.items[0]?.id || "");
          const last = Math.max(1, Math.ceil(page.total / rolePageSize)); if (rolePage > last) setRolePage(last);
        }, current);
        if (success && valid() && loadedRows) {
          updateMappingProjection();
          const memberships = await Promise.all(loadedRows.map(role => readRoleMembers({ id: role.id }, valid)));
          return memberships.every(Boolean) && valid();
        }
        return success && valid();
      }
      case "models": return readSystemSection(section, () => listModels(apiFetch), rows => { setLiveModels(rows.map(modelRow)); setPromptModelDraft(selected => selected || rows.find(model => ["Chat", "Judge"].includes(model.model_type))?.id || ""); }, current);
      case "prompts": return readSystemSection(section, () => listSystemPrompts(apiFetch), rows => {
        setSystemPrompts(rows);
        if (!draftStates.current.prompts) { const next = rows.find(row => row.id === selectedPromptId) ?? rows[0]; setSelectedPromptId(next?.id ?? ""); setPromptDraft(next?.content ?? ""); setPromptBaseline(next?.content ?? ""); setPromptDraftSourceVersion(null); }
      }, current);
      case "projects": return readSystemSection(section, () => listProjectsPage(apiFetch, { q: projectQuery, offset: projectOffset, limit: 20 }), page => { cacheProjects(page.items); setProjectTotal(page.total); setProjectCandidateIds(ids => projectOffset === 0 ? page.items.map(row => row.id) : [...new Set([...ids, ...page.items.map(row => row.id)])]); }, current);
      case "memberCandidates": return readSystemSection(section, () => listUsersPage(apiFetch, { q: roleUserSearch, isActive: true, offset: memberOffset, limit: 20 }), page => { cacheUsers(page.items); setMemberTotal(page.total); setMemberCandidateIds(ids => memberOffset === 0 ? page.items.map(row => row.id) : [...new Set([...ids, ...page.items.map(row => row.id)])]); }, current);
      case "clients": return readSystemSection(section, () => listIntegrationClientsPage(apiFetch, { name: clientQuery, cursor: clientCursors.at(-1), limit: clientPageSize }), page => { setIntegrationClients(page.items); setClientNextCursor(page.has_more ? page.next_cursor : null); }, current);
      case "syncRuns": return readSystemSection(section, () => listIdentitySyncRuns(apiFetch), setSyncRuns, current);
      case "groups": { const success = await readSystemSection(section, () => listExternalGroups(apiFetch), rows => { groupRows.current = rows; setExternalGroups(rows); }, current); if (success && current()) updateMappingProjection(); return success; }
      case "mappings": { const success = await readSystemSection(section, () => listExternalGroupMappings(apiFetch), rows => { mappingRows.current = rows; }, current); if (success && current()) updateMappingProjection(); return success; }
      case "breakGlass": return readSystemSection(section, () => getBreakGlassStatus(apiFetch), setBreakGlassStatus, current);
      case "status": return readSystemSection(section, () => getSystemStatus(apiFetch), setSystemStatus, current);
      default: return false;
    }
  }
  async function loadSystem() {
    if (!canViewSystemManagement) { setSystemLoading(false); return; }
    const scope = systemReadScope;
    if (loadedSystemScope !== scope) {
    setLiveUsers([]); setLiveRoles([]); setLiveProjects([]); setIntegrationClients([]);
    setLiveModels([]); setModelTableRows([]); setModelTableReceived(false); modelTableRequestRef.current++;
    setSystemPrompts([]); setLiveGroupMappings([]); setExternalGroups([]); setSyncRuns([]); setSystemStatus(null); setBreakGlassStatus(null);
    setUserTableIds([]); setRoleTableIds([]); setProjectCandidateIds([]); setMemberCandidateIds([]);
    setUserOverallTotal(null); setRoleOverallTotal(null); setSelectedRole("");
    setUserPage(1); setRolePage(1); setClientCursors([undefined]); setProjectOffset(0); setMemberOffset(0);
    }
    setSystemLoading(true); setSystemError(null);
    const resources: Record<SettingsPosition["section"], string[]> = { people: ["users", "roles", "groups", "mappings"], identity: ["breakGlass"], ai: ["models", "prompts"], apiKeys: ["projects", "clients"], status: ["status"], general: [], documents: [] };
    await Promise.all(resources[activeSection].map(section => reloadSystemSection(section)));
    if (systemReadScopeRef.current !== scope) return;
    setLoadedSystemScope(scope); setLiveReady(true); setSystemLoading(false);
  }
  function renderSectionReadNotice(section: string, title?: string, announce = true) {
    const state = sectionReads[section];
    if (!state || state.scope !== systemReadScope || state.phase === "ready" || state.phase === "loading") return null;
    return <FeedbackMessage announce={announce} tone={state.phase === "forbidden" ? "warning" : "error"} title={title ?? t("systemReadFailedTitle")} actions={<button className="action-button secondary" onClick={() => { const role = liveRoles.find(row => section === `members:${row.id}`); if (role) void readRoleMembers(role); else void reloadSystemSection(section); }} type="button">{t("retry")}</button>}>
      {state.phase === "forbidden" ? t("apiForbidden") : errorMessage(state.error!)} {state.received ? t("systemReadStale") : t("systemReadUnknown")}
    </FeedbackMessage>;
  }

  const refreshModelTable = useCallback(async () => {
    if (!canViewSystemManagement) return;
    const requestId = ++modelTableRequestRef.current;
    setModelTableLoading(true);
    setModelTableError("");
    try {
      const page = await listModelsPage(apiFetch, {
        modelType: modelTableType === "all" ? undefined : modelTableType,
        offset: (modelTablePage - 1) * modelTablePageSize,
        limit: modelTablePageSize
      });
      if (requestId !== modelTableRequestRef.current) return;
      const totalPages = Math.max(1, Math.ceil(page.total / modelTablePageSize));
      if (modelTablePage > totalPages) {
        setModelTablePage(totalPages);
        return;
      }
      setModelTableRows(page.rows.map(modelRow));
      setModelTableTotal(page.total); setModelTableReceived(true);
    } catch (caught) {
      if (requestId === modelTableRequestRef.current) {
        setModelTableError(errorMessage(caught as ApiError | Error));
      }
    } finally {
      if (requestId === modelTableRequestRef.current) setModelTableLoading(false);
    }
  }, [apiFetch, canViewSystemManagement, errorMessage, modelTablePage, modelTablePageSize, modelTableType, setModelTableError, setModelTableLoading, setModelTablePage, setModelTableReceived, setModelTableRows, setModelTableTotal]);
  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const modelActions = createModelActions(modelState, { apiFetch, modal, notify, refreshModelTable, reloadSystemSection, runModalMutation, runQuickMutation, setLiveModels, setModal, setModalError, setSystemError, t });
  const { refreshModels } = modelActions;

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadSystem(); }, 0);
    return () => window.clearTimeout(timer);
  }, [canViewSystemManagement, systemReadScope, activeSection]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeSection === "identity" && new URL(window.location.href).searchParams.has("reauth")) return;
    window.history.replaceState(window.history.state, "", settingsPositionUrl(window.location.href, position));
  }, [position, activeSection]);
  useEffect(() => {
    if (!liveReady) return;
    const timer = window.setTimeout(() => {
      const target = document.getElementById(`settings-panel-${position.panel}`);
      target?.scrollIntoView({ block: "start", behavior: "instant" });
      target?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [position, liveReady, loadedSystemScope]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (!permissionSaved || identityDirty || parameterDirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeUnload); return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [permissionSaved, identityDirty, parameterDirty]);

  useEffect(() => {
    if (activeTab !== "models" || !liveReady) return;
    const timer = window.setTimeout(() => { void refreshModelTable(); }, 0);
    return () => window.clearTimeout(timer);
  }, [activeTab, liveReady, refreshModelTable]);

  useEffect(() => {
    if (activeSection !== "people" || !liveReady || !selectedRole || !selectedRoleReady || !permissionSaved) return;
    let current = true;
    getPermissions(apiFetch, selectedRole).then((response) => {
      if (!current) return;
      setPermissions((current) => ({ ...current, [selectedRole]: permissionStateFromResponse(response) }));
      setLiveRoles((current) => current.map((role) => role.id === selectedRole ? { ...role, lockVersion: response.lock_version } : role));
      setPermissionSaved(true);
    }).catch((caught) => { if (current) setSystemError(caught as ApiError | Error); });
    return () => { current = false; };
  }, [activeSection, apiFetch, liveReady, selectedRole, selectedRoleReady, selectedRoleLockVersion, permissionSaved, setLiveRoles, setPermissionSaved, setPermissions]);

  useEffect(() => {
    if (!canViewSystemManagement || activeSection !== "people") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("users"); }, 300);
    return () => { clearTimeout(timer); versions.users = (versions.users ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, apiFetch, systemReadScope, canViewSystemManagement, userQuery, userSourceFilter, userPage, userPageSize]);
  useEffect(() => {
    if (!canViewSystemManagement || activeSection !== "people") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("roles"); }, 300);
    return () => { clearTimeout(timer); versions.roles = (versions.roles ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, apiFetch, systemReadScope, canViewSystemManagement, roleQuery, roleStatusFilter, rolePage, rolePageSize]);
  useEffect(() => {
    if (!canViewSystemManagement || activeSection !== "apiKeys") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("clients"); }, 300);
    return () => { clearTimeout(timer); versions.clients = (versions.clients ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, apiFetch, systemReadScope, canViewSystemManagement, clientQuery, clientCursors, clientPageSize]);
  useEffect(() => {
    if (!canViewSystemManagement || activeSection !== "apiKeys") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("projects"); }, 300);
    return () => { clearTimeout(timer); versions.projects = (versions.projects ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, apiFetch, systemReadScope, canViewSystemManagement, projectQuery, projectOffset]);
  useEffect(() => {
    if (!canViewSystemManagement || modal?.type !== "role-users") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("memberCandidates"); }, 300);
    return () => { clearTimeout(timer); versions.memberCandidates = (versions.memberCandidates ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, modal?.type, modal?.type === "role-users" ? modal.role.id : null, roleUserSearch, memberOffset]);
  function renderListPager(section: string, page: number, size: number, total: number | null, previous: () => void, next: (() => void) | null, changeSize: (size: number) => void) {
    const busy = !sectionReady(section);
    return <Pagination buttonClassName="action-button secondary" canNext={!busy && Boolean(next)} canPrevious={!busy && page > 1} className="model-list-pagination" iconSize={15} leading={<label><span>{t("systemRowsPerPage")}</span><DropdownSelect aria-label={t("systemRowsPerPage")} disabled={busy} onChange={event => changeSize(Number(event.target.value))} value={size}>{[20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</DropdownSelect></label>} nextLabel={t("adminNext")} onNext={() => next?.()} onPrevious={previous} previousLabel={t("adminPrevious")} summary={total === null ? format("adminListBatch", { page: formatCount(page, locale) }) : format("systemPageOf", { page: formatCount(page, locale), total: formatCount(Math.max(1, Math.ceil(total / size)), locale) })} variant="text" />;
  }
  function renderProjectSearch() { return <><label className="system-toolbar"><Search size={16} /><input aria-label={t("adminSearchProjects")} maxLength={100} onChange={event => { setProjectQuery(event.target.value); setProjectOffset(0); }} placeholder={t("adminSearchProjects")} value={projectQuery} /></label><span>{format("adminSelectedCount", { count: formatCount(modal?.type === "api-key-manage" ? (apiKeyScopeDrafts[modal.client.id] ?? modal.client.project_ids).length : apiKeyProjectDraft.length, locale) })}</span>{projectCandidateIds.length < projectTotal ? <button className="action-button secondary" disabled={!sectionReady("projects")} onClick={() => setProjectOffset(offset => offset + 20)} type="button">{t("adminLoadMore")}</button> : null}</>; }

  const userRowName = (user: UserRow) => formatPersonName(user.raw ?? { display_name: user.name }, locale) || user.name;
  const filteredUsers = userTableIds.flatMap(id => liveUsers.find(row => row.id === id) ?? []);
  const filteredLocalRoles = roleTableIds.flatMap(id => liveRoles.find(row => row.id === id) ?? []);
  const roleUserRows = roleUsers?.users ?? [];
  const originalManualRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "manual").map((row) => row.user_id));
  const externalRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "external_sync").map((row) => row.user_id));
  const breakGlassRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "break_glass").map((row) => row.user_id));
  const draftRoleUserIds = new Set(roleUserDraftIds);
  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const roleActions = createRoleActions(roleState, { apiFetch, breakGlassRoleUserIds, canDeleteRoles, canEditPermissions, canEditRoles, draftRoleUserIds, externalRoleUserIds, format, groupRows, mappingRows, modal, originalManualRoleUserIds, quickBlocked, readSystemSection, reloadSystemSection, renderSectionReadNotice, roleNames, runModalMutation, runQuickMutation, sectionReady, selectedRoleReadOnly, setModal, setModalError, setSystemError, systemReadScope, systemReadStates, t });
  const { cacheRoles, applyMemberSnapshot, updateMappingProjection, readRoleMembers, refreshRolesAndMappings } = roleActions;
  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const identityActions = createIdentityActions(identityState, { apiFetch, errorMessage, refreshRolesAndMappings, reloadSystemSection, sectionReady, t });
  const { runIdentitySync } = identityActions;
  const activeRoleUserCandidates = liveUsers.filter((user) => user.status === "active" && memberCandidateIds.includes(user.id));
  const filteredRoleUserCandidates = activeRoleUserCandidates;
  const pendingAddUsers = liveUsers.filter((user) => user.status === "active" && draftRoleUserIds.has(user.id) && !originalManualRoleUserIds.has(user.id));
  const pendingRemoveUsers = liveUsers.filter((user) => originalManualRoleUserIds.has(user.id) && !draftRoleUserIds.has(user.id));
  const activeProjects = projectCandidateIds.flatMap(id => liveProjects.find(project => project.id === id && project.status === "active") ?? []);
  const projectNameById = new Map(liveProjects.map((project) => [project.id, project.name]));
  const ldapGroups = externalGroups.filter((group) => ["ldap", "ad"].includes(group.identity_origin));
  const mappingRole = modal?.type === "mapping" ? modal.role : null;
  const availableMappingGroups = ldapGroups.filter((group) => group.is_active && (!group.mapped_role_id || group.mapped_role_id === mappingRole?.id));
  const modelTableTotalPages = Math.max(1, Math.ceil(modelTableTotal / modelTablePageSize));
  const modelTableFirst = modelTableTotal ? (modelTablePage - 1) * modelTablePageSize + 1 : 0;
  const modelTableLast = Math.min(modelTablePage * modelTablePageSize, modelTableTotal);

  function requestSettingsLeave(action: () => void) {
    if (!permissionSaved || parameterDirty || identityDirty || apiKeyOneTime) {
      leaveFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setSettingsLeave(() => action);
    } else action();
  }
  function navigateSettings(next: SettingsPosition) {
    if (next.section === activeSection) { setPosition(next); setNavOpen(false); setSettingsSearch(""); return; }
    requestSettingsLeave(() => {
      const commit = () => { setApiKeyOneTime(null); setParameterDirty(false); setIdentityDirty(false); setPermissionSaved(true); setPosition(next); setNavOpen(false); setSettingsSearch(""); };
      if (activeSection === "identity") {
        void apiFetch(`${apiBaseUrl()}/system/identity-settings/lock`, { method: "POST" }).then(response => {
          if (!response.ok) throw new Error("identity_settings_locked");
          commit();
        }).catch(error => setSystemError(error));
      } else commit();
    });
  }

  async function refreshSystemStatus() { await reloadSystemSection("status"); }

  function setModal(next: React.SetStateAction<ModalState | null>) {
    if (typeof next !== "function") {
      if (modalScope(next) !== modalScope(modal)) { setModalError(""); setModalQueryMessage(""); setModalReadback(""); }
      if (!next) setSubmitting(false);
    }
    setModalState(next);
  }

  async function runModalMutation<T>(write: (accepted: () => void, current: () => boolean) => Promise<T>, apply: (result: T, current: () => boolean) => void | Promise<void>, title: TranslationKey = "feedbackSaved") {
    const token = modalGuard.begin(); if (token === null) return;
    modalEventId.current = crypto.randomUUID(); modalReceiptId.current = null;
    modalMutationScope.current = modalGuard.scope;
    setSubmitting(true); setModalError(""); setModalQueryMessage(""); setModalReadback(""); modalSuccess.current = title;
    try {
      const result = await write(() => modalGuard.accepted(token), () => modalGuard.current(token));
      if (!modalGuard.current(token)) return;
      modalGuard.accepted(token);
      if (result && typeof result === "object" && "id" in result && typeof result.id === "string") modalReceiptId.current = result.id;
      setDirtyModal(null);
      await apply(result, () => modalGuard.current(token));
      if (!modalGuard.current(token)) return;
      setSubmitting(false); setDirtyModal(null); modalGuard.complete(token); setModal(null);
      notify({ id: modalEventId.current, scope: "system", tone: "success", title });
    } catch (caught) {
      if (!modalGuard.current(token)) return;
      modalGuard.failed(token, caught);
      setModalError(modalGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : errorMessage(caught as ApiError | Error));
    } finally { if (modalGuard.current(token)) setSubmitting(false); }
  }

  async function runQuickMutation(target: NonNullable<typeof quickTarget.current>, write: () => Promise<unknown>, refresh: (current: () => boolean) => Promise<void>) {
    const token = quickGuard.begin(); if (token === null) return;
    quickTarget.current = target; setQuickError(null); setQuickQueryFailed(false);
    try {
      await write(); if (!quickGuard.current(token)) return;
      quickGuard.accepted(token); await refresh(() => quickGuard.current(token)); if (!quickGuard.current(token)) return;
      quickGuard.complete(token);
      notify({ id: crypto.randomUUID(), scope: "system", tone: "success", title: "feedbackSaved" });
    } catch (caught) {
      if (!quickGuard.current(token)) return;
      quickGuard.failed(token, caught); setQuickError(caught as ApiError | Error);
    }
  }

  useGuardedLinkNavigation({ apiFetch, identityActive: activeSection === "identity", promptEditorOpen, requestPromptLeave, requestSettingsLeave, setSystemError, unsaved: !permissionSaved || parameterDirty || identityDirty });

  function closeModal() {
    if (submitting) return;
    if (modal && dirtyModal === modal) { setDiscardModal(modal); return; }
    const restoreTarget = modal?.type === "role-delete" ? roleMenuTriggerRef.current : null;
    setModal(null);
    if (restoreTarget) window.requestAnimationFrame(() => restoreTarget.focus());
  }

  const selectedPrompt = systemPrompts.find((prompt) => prompt.id === selectedPromptId);
  const activePromptEditor = promptEditorOpen ? (selectedPrompt ?? promptEditorPrompt) : null;
  const promptModels = liveModels.filter((model) => model.type === "Chat" || model.type === "Judge");
  const promptModelOptions = promptModels.filter((model) => !systemPrompts.some((prompt) => prompt.model_id === model.id));
  const globalChatPrompt = systemPrompts.find((prompt) => prompt.prompt_scope === "global" && prompt.model_type === "Chat");
  const globalJudgePrompt = systemPrompts.find((prompt) => prompt.prompt_scope === "global" && prompt.model_type === "Judge");
  const modelSpecificPrompts = systemPrompts.filter((prompt) => prompt.prompt_scope === "model");
  const promptScopeLabel = (prompt: PromptRow) => prompt.prompt_scope === "global" ? t("systemPromptScopeGlobal") : t("systemPromptScopeModel");

  // The factory only creates handlers; ref-reading dependencies run in events, not during render.
  // eslint-disable-next-line react-hooks/refs
  const { queryModalOutcome, queryQuickOutcome } = createOutcomeQueries({ apiFetch, applyMemberSnapshot, cacheRoles, cacheUsers, format, groupRows, locale, localizedStatus, mappingRows, modal, modalEventId, modalGuard, modalMutationScope, modalReceiptId, modalSuccess, notify, quickGuard, quickTarget, refreshModels, refreshRolesAndMappings, setDirtyModal, setIntegrationClients, setLiveModels, setModal, setModalError, setModalQueryMessage, setModalReadback, setModelTableRows, setQuickError, setQuickQueryFailed, setReadState, setRoleUsersReadback, systemReadScope, systemReadVersions, t, updateMappingProjection });

  if (!canViewSystemManagement) {
    return <ForbiddenState />;
  }

  if (loadedSystemScope !== systemReadScope) return <FeedbackMessage tone="info">{t("loadingData")}</FeedbackMessage>;

  // Views receive event handlers that read refs only when the user acts, never during render.
  // eslint-disable-next-line react-hooks/refs
  const { renderApiKeyPanel, renderApiKeyCreateForm, renderApiKeyManageForm } = createApiKeyView(apiKeyState, apiKeyActions, { activeProjects, canCreateSystemManagement, canDeleteSystemManagement, canEditSystemManagement, clientNextCursor, closeModal, discardModal, format, modal, modalBlocked, projectNameById, renderListPager, renderProjectSearch, renderSectionReadNotice, sectionReady, setModal, submitting, t });
  // Views receive event handlers that read refs only when the user acts, never during render.
  // eslint-disable-next-line react-hooks/refs
  const { renderModelPanel, renderModelForm, renderModelDeleteForm } = createModelView(modelState, modelActions, { activeEmbeddingModels, apiFetch, canCreateModels, canDeleteModels, canEditModels, closeModal, discardModal, format, locale, localize, localizedOperationStatus, localizedStatus, modal, modalBlocked, modelTableFirst, modelTableLast, modelTableTotalPages, quickBlocked, refreshModelTable, runQuickMutation, sectionReady, setModal, submitting, t });
  const { renderPromptPanel } = createPromptView(promptState, promptActions, { canCreateModels, format, globalChatPrompt, globalJudgePrompt, liveModels, modelSpecificPrompts, promptBlocked, promptModelOptions, sectionReady, t });
  // Views receive event handlers that read refs only when the user acts, never during render.
  // eslint-disable-next-line react-hooks/refs
  const { renderRolePanel, renderPermissionPanel, renderRoleForm, renderRoleUsersForm, renderRoleMappingForm, renderRoleDeleteForm } = createRoleView(roleState, roleActions, { activeRoleUserCandidates, availableMappingGroups, breakGlassRoleUserIds, canCreateRoles, canEditPermissions, canEditRoles, closeModal, discardModal, draftRoleUserIds, externalRoleUserIds, filteredLocalRoles, filteredRoleUserCandidates, format, ldapGroups, liveUsers, locale, modal, modalBlocked, originalManualRoleUserIds, pendingAddUsers, pendingRemoveUsers, renderListPager, renderSectionReadNotice, requestSettingsLeave, sectionReady, selectedRoleReadOnly, setModal, submitting, t, userRowName });
  // Views receive event handlers that read refs only when the user acts, never during render.
  // eslint-disable-next-line react-hooks/refs
  const { renderUserPanel, renderUserForm } = createUserView(userState, userActions, { canEditUsers, closeModal, discardModal, filteredUsers, format, locale, localizedStatus, modal, modalBlocked, renderListPager, runIdentitySync, sectionReads, sectionReady, setModal, submitting, t, userRowName });
  const { renderIdentityPanel } = createIdentityView(identityState, identityActions, { canEditSystemManagement, format, locale, renderSectionReadNotice, systemReadScope, t });
  return (
    <section className="system-workspace">
      {systemLoading ? <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("loadingData")}</strong><span>{t("systemLoadingBackend")}</span></div></div> : null}
      {quickError ? <FeedbackMessage tone={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? "warning" : "error"} actions={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? <button type="button" className="action-button secondary" disabled={quickOperation.checking} onClick={() => void queryQuickOutcome()}>{t("feedbackQueryOutcome")}</button> : undefined}><strong>{quickOperation.checking ? t("feedbackCheckingOutcome") : quickOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : quickOperation.phase === "unknown" ? t("feedbackResultUnknown") : errorMessage(quickError)}</strong>{quickQueryFailed ? <p>{t("feedbackOutcomeQueryFailed")}</p> : null}{quickOperation.phase === "unknown" && quickOperation.checked ? <p>{t("feedbackSystemOutcomeChecked")}</p> : null}</FeedbackMessage> : null}
      {systemError ? <FeedbackMessage tone="error"><strong>{errorMessage(systemError)}</strong><button className="text-link" onClick={loadSystem} type="button">{t("retry")}</button></FeedbackMessage> : null}
      {settingsLeave ? <div className="system-modal-backdrop"><section ref={leaveDialogRef} role="alertdialog" aria-modal="true" aria-labelledby="settings-leave-title" className="system-reauth-modal"><h2 id="settings-leave-title">{t("contentEditUnsaved")}</h2><FeedbackConfirm title={t("settingsLeaveHelp")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => { setSettingsLeave(null); leaveFocus.current?.focus(); }} onConfirm={() => { const action = settingsLeave; setSettingsLeave(null); if (!permissionSaved) setPermissions(previous => { const next = { ...previous }; delete next[selectedRole]; return next; }); action(); }} /></section></div> : null}
      <button className="action-button secondary settings-menu-trigger" aria-expanded={navOpen} aria-controls="settings-navigation" onClick={() => setNavOpen(true)} type="button"><Settings2 size={18} />{t("settingsCategories")}</button>
      <div className="system-settings-layout">
        <SettingsNavigation activeSection={activeSection} leaveOpen={Boolean(settingsLeave)} narrow={narrow} navOpen={navOpen} navigateSettings={navigateSettings} navigationRef={navigationRef} setNavOpen={setNavOpen} setSettingsSearch={setSettingsSearch} settingsSearch={settingsSearch} t={t} />
        <div className="settings-main" inert={Boolean(settingsLeave) || narrow && navOpen}>
          <header className="settings-page-heading"><p>{t("labelSystemManagement")}</p><h1>{t(settingsSections.find(section => section.id === activeSection)!.labelKey)}</h1><span>{t("settingsWorkspaceHelp")}</span></header>
          {activeSection === "general" ? <button type="button" className="text-link" onClick={() => navigateSettings({ section: "documents", panel: "upload" })}>{t("settingsGoDocuments")}<ChevronRight size={16} /></button> : null}
          {(activeSection === "people" ? ["users", "roles", "groups", "mappings"] : activeSection === "ai" ? ["models", "prompts"] : activeSection === "apiKeys" ? ["clients", "projects"] : activeSection === "status" ? ["status"] : []).map(section => <div key={section}>{renderSectionReadNotice(section)}</div>)}
          {activeSection === "people" ? renderUserPanel() : null}
          {activeSection === "people" ? renderRolePanel() : null}
          {activeSection === "people" ? renderPermissionPanel() : null}
          {activeSection === "ai" ? renderModelPanel() : null}
          {activeSection === "ai" ? renderPromptPanel() : null}
          {activeSection === "apiKeys" ? renderApiKeyPanel() : null}
          {activeTab === "identity" ? renderIdentityPanel() : null}
          {activeTab === "status" ? <>
            <SectionHeader action={<button className="action-button secondary" onClick={() => { void refreshSystemStatus(); }} type="button"><RefreshCw size={16} />{t("refresh")}</button>} description={t("systemStatusDescription")} title={t("systemStatus")} />
            <div className="fixture-banner"><Activity size={17} /><div><strong>{t("liveData")}</strong><span>{t("systemStatusLiveHelp")}</span></div></div>
            <SystemStatusPanel ready={sectionReady("status")} status={systemStatus} />
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemSecurityMasking")}</strong><p>{t("systemSecurityMaskingHelp")}</p></div></div>
          </> : null}

          {activeSection === "general" || activeSection === "documents" ? <SystemParameterSettings key={`${systemReadScope}:${activeSection}`} section={activeSection} onDirtyChange={setParameterDirty} /> : null}
        </div>
      </div>
      {activePromptEditor ? <div className="system-modal-backdrop" onKeyDown={handlePromptDialogKey} onMouseDown={(event) => { if (event.target === event.currentTarget) requestPromptLeave(() => setPromptEditorOpen(false)); }} role="presentation">
        <section ref={promptDialogRef} aria-labelledby="system-prompt-editor-title" aria-modal="true" className="system-prompt-modal" role="dialog">
          <header><span><MessageSquareText size={20} /></span><div className="system-prompt-title-row"><h2 id="system-prompt-editor-title">{t("systemPromptEditor")}</h2><div className="system-prompt-badges"><StateBadge tone={activePromptEditor.prompt_scope === "global" ? "green" : "gold"}>{promptScopeLabel(activePromptEditor)}</StateBadge><StateBadge>{activePromptEditor.model_type}</StateBadge><StateBadge tone={activePromptEditor.is_active ? "green" : "gray"}>{activePromptEditor.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></div></div><button aria-label={t("systemPromptCloseEditor")} autoFocus className="modal-close-button" disabled={promptSaving} onClick={() => requestPromptLeave(() => setPromptEditorOpen(false))} type="button"><X size={18} /></button></header>
          {renderPromptFeedback()}
          {promptLeave ? <FeedbackConfirm title={t("contentEditUnsaved")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => { setPromptLeave(null); promptFocusRef.current?.focus(); }} onConfirm={() => { const action = promptLeave; setPromptLeave(null); setPromptDraft(promptBaseline); action(); }}>{promptOperation.phase === "unknown" ? t("feedbackUnknownCloseHelp") : undefined}</FeedbackConfirm> : null}
          <div inert={Boolean(promptLeave)}>{renderPromptEditor(activePromptEditor)}</div>
        </section>
      </div> : null}
      {apiKeyOneTime && !modal ? <ApiKeyOneTimeDialog apiKey={apiKeyOneTime} dialogRef={apiKeyDialogRef} format={format} onClose={() => setApiKeyOneTime(null)} t={t} /> : null}
      {modal ? <div className="system-modal-backdrop" onKeyDown={(event) => {
        if (event.key === "Escape" && !submitting) { event.stopPropagation(); if (discardModal === modal) setDiscardModal(null); else closeModal(); }
        if (event.key === "Tab") {
          const dialog = systemDialogRef.current;
          const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]') ?? []).filter(control => control.getClientRects().length && !control.closest('[inert]'));
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
        }
      }} onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) closeModal(); }} role="presentation">
        <section ref={systemDialogRef} aria-labelledby="system-crud-modal-title" aria-modal="true" onChangeCapture={() => setDirtyModal(modal)} className={`system-reauth-modal system-crud-modal${modal.type === "role-users" ? " role-user-modal" : modal.type === "model-delete" ? " model-delete-modal" : modal.type === "role-delete" ? " role-delete-modal" : ""}`} role={modal.type === "role-delete" ? "alertdialog" : "dialog"}>
          <header><span>{modal.type === "api-key-create" || modal.type === "api-key-manage" ? <KeyRound size={20} /> : modal.type === "model-delete" || modal.type === "role-delete" ? <Trash2 size={20} /> : <Settings2 size={20} />}</span><div><small>{t("labelSystemManagement")}</small><h2 id="system-crud-modal-title">{modal.type === "user" ? t("systemUserDetails") : modal.type === "role" ? (modal.role ? (modal.role.isActive === false ? t("systemRoleDetails") : t("systemEditRole")) : t("systemAddRole")) : modal.type === "role-users" ? t("systemManualRoleUsers") : modal.type === "mapping" ? t("systemRoleMappingTitle") : modal.type === "role-delete" ? t("systemDeleteLocalRole") : modal.type === "model" ? (modal.model ? t("systemEditAiModel") : t("systemAddAiModel")) : modal.type === "model-delete" ? t("systemDeleteModelTitle") : modal.type === "api-key-create" ? t("systemApiKeyCreateTitle") : modal.type === "api-key-manage" ? t("systemApiKeyManageTitle") : localize(modal.title)}</h2></div><button aria-label={t("close")} className="modal-close-button" disabled={submitting} onClick={closeModal} type="button"><X size={18} /></button></header>
          {discardModal === modal ? <FeedbackConfirm title={t("contentEditUnsaved")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => { setDiscardModal(null); systemDialogRef.current?.querySelector<HTMLButtonElement>(".modal-close-button")?.focus(); }} onConfirm={() => { setDiscardModal(null); setDirtyModal(null); setModal(null); }} /> : null}
          {modalFeedbackError ? <FeedbackMessage tone={modalOperation.phase === "unknown" || modalOperation.phase === "read_failed" ? "warning" : "error"} actions={modalOperation.phase === "unknown" || modalOperation.phase === "read_failed" ? <button type="button" className="action-button secondary" disabled={modalOperation.checking} onClick={() => void queryModalOutcome()}>{t(modalOperation.phase === "read_failed" ? "feedbackReloadResult" : "feedbackQueryOutcome")}</button> : undefined}><strong>{localize(modalFeedbackError)}</strong>{modalQueryMessage ? <p>{modalQueryMessage}</p> : null}{modalReadback ? <p>{modalReadback}</p> : null}</FeedbackMessage> : null}
          {modal.type === "user" ? renderUserForm(modal) : null}
          {modal.type === "role" ? renderRoleForm(modal) : null}
          {modal.type === "role-users" ? renderRoleUsersForm(modal) : null}
          {modal.type === "mapping" ? renderRoleMappingForm(modal) : null}
          {modal.type === "role-delete" ? renderRoleDeleteForm(modal) : null}
          {modal.type === "model" ? renderModelForm(modal) : null}
          {modal.type === "model-delete" ? renderModelDeleteForm(modal) : null}
          {modal.type === "api-key-create" ? renderApiKeyCreateForm() : null}
          {modal.type === "api-key-manage" ? renderApiKeyManageForm(modal) : null}
          {modal.type === "confirm" ? <div className="system-crud-form"><p>{localize(modal.message)}</p><footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked} onClick={() => { void runModalMutation(modal.run, () => {}, modal.successTitle); }} type="button">{localize(modal.actionLabel)}</button></footer></div> : null}
        </section>
      </div> : null}
    </section>
  );
}
