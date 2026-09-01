"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  DatabaseZap,
  Ellipsis,
  Eye,
  FileCheck2,
  Globe2,
  Info,
  KeyRound,
  Link2,
  LoaderCircle,
  LockKeyhole,
  LogIn,
  MessageSquareText,
  Layers3,
  Plus,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Unlink,
  UserRoundCog,
  UsersRound,
  X
} from "lucide-react";
import {
  getIdentitySettings,
  getIdentitySyncRun,
  getBreakGlassStatus,
  getPermissions,
  getRoleUsers,
  getSystemParameters,
  getSystemStatus,
  activateIntegrationClient,
  createIntegrationClient,
  listSystemPrompts,
  listExternalGroupMappings,
  listExternalGroups,
  listDirectoryProviders,
  listIntegrationClients,
  listModels,
  listModelsPage,
  listProjects,
  listRoles,
  listUsers,
  deactivateIntegrationClient,
  replaceIntegrationClientProjectScopes,
  replacePermissions,
  replaceRoleUsers,
  revokeIntegrationClient,
  rotateIntegrationClientKey,
  updateIntegrationClient,
  updateSystemParameters,
  addSystemPromptVersion,
  activateSystemPrompt,
  createSystemPrompt,
  deactivateSystemPrompt,
  type AIModelResponse,
  type AIModelPayload,
  type ApiError,
  type BreakGlassStatusResponse,
  type DirectoryProviderResponse,
  type ExternalGroupResponse,
  type IdentitySettingsCandidate,
  type IdentitySyncRunResponse,
  type IntegrationClientResponse,
  type OperationComponentStatus,
  type OperationsStatusResponse,
  type PermissionMatrixResponse,
  type ProjectResponse,
  type RoleResponse,
  type RoleUsersResponse,
  type SystemPromptResponse,
  type UserSummary,
  activateIdentitySettings,
  completeIdentityReauth,
  createModel,
  createRole,
  deleteRole,
  deleteModel,
  listIdentitySyncRuns,
  lockIdentitySettings as lockIdentitySettingsApi,
  queueIdentitySync,
  setDefaultModel,
  setRoleExternalGroupMapping,
  startIdentityReauth,
  testModel,
  updateModel,
  updateDirectoryProviderFilter,
  updateRole,
  updateUser,
  updateUserStatus,
  validateIdentitySettingsCandidate
} from "@/lib/api";
import { AIModelCredentialClearControl, OpenAiApiModeField } from "@/components/AIModelCompatibilityFields";
import { aiModelProviderName } from "@/components/AIModelInventoryFields";
import { ForbiddenState } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import {
  emptyIdentitySettings,
  defaultSystemParameters,
  hasParameterErrors,
  identityUnlockDurationMs,
  validateIdentitySettings,
  type IdentitySettings,
  validateSystemParameters,
  type SystemParameterValues
} from "@/lib/systemManagement";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName, personNameSearchText } from "@/lib/personName";
import {
  parseIdentityReauthResult,
  systemRouteUrl,
  type IdentityReauthResult,
  type SystemTabId
} from "@/lib/systemRouteState";

const tabs = [
  { id: "users", labelKey: "systemUsers", icon: UsersRound },
  { id: "roles", labelKey: "systemRoles", icon: UserRoundCog },
  { id: "permissions", labelKey: "systemPermissions", icon: ShieldCheck },
  { id: "models", labelKey: "systemModels", icon: Bot },
  { id: "prompts", labelKey: "systemPrompts", icon: MessageSquareText },
  { id: "apiKeys", labelKey: "systemApiKeys", icon: KeyRound },
  { id: "identity", labelKey: "systemIdentity", icon: KeyRound },
  { id: "status", labelKey: "systemStatus", icon: Activity },
  { id: "parameters", labelKey: "systemParameters", icon: SlidersHorizontal }
] as const;

type IdentityReauthStatus = "ready" | "opening" | "completing" | "error";

const identityValidationMessageKeys = {
  issuer: "identityValidationIssuerHttps",
  realm: "identityValidationRealmRequired",
  clientId: "identityValidationClientIdRequired",
  audience: "identityValidationAudienceRequired",
  discoveryUrl: "identityValidationDiscoveryHttps",
  schedule: "identityValidationScheduleCron",
  timezone: "identityValidationTimezoneIana"
} as const satisfies Partial<Record<keyof IdentitySettings, TranslationKey>>;

type IdentityValidationField = keyof typeof identityValidationMessageKeys;

const permissionMenuRows = [
  { key: "Menu.KnowledgeProjects", moduleName: "Menu", functionName: "KnowledgeProjects", labelKey: "systemMenuKnowledgeProjects", descriptionKey: "systemMenuKnowledgeProjectsHelp", actions: ["view", "create"] },
  { key: "Menu.Reports", moduleName: "Menu", functionName: "Reports", labelKey: "systemMenuReports", descriptionKey: "systemMenuReportsHelp", actions: ["view"] },
  { key: "Menu.SystemManagement", moduleName: "Menu", functionName: "SystemManagement", labelKey: "systemMenuSystemManagement", descriptionKey: "systemMenuSystemManagementHelp", actions: ["view", "create", "edit", "delete"] },
  { key: "Project.ProjectArchive", moduleName: "Project", functionName: "ProjectArchive", labelKey: "systemProjectArchive", descriptionKey: "systemProjectArchiveHelp", actions: ["execute"] },
  { key: "Report.ModelReport", moduleName: "Report", functionName: "ModelReport", labelKey: "systemReportModelReport", descriptionKey: "systemReportModelReportHelp", actions: ["view"] }
] as const;

type TabId = SystemTabId;
type PermissionAction = "view" | "create" | "edit" | "delete" | "execute";
type PermissionState = Record<string, Record<PermissionAction, boolean>>;
type UserRow = { id: string; name: string; email: string; department: string; source: string; roles: string; status: string; raw?: UserSummary };
type RoleRow = { id: string; name: string; members: number; manualMembers: number; ldapMembers: number; breakGlassMembers: number; groups: number; mappingGroupId: string | null; description: string | null; lockVersion: number; isSystem?: boolean; isActive?: boolean };
type RoleStatusFilter = "all" | "enabled" | "disabled";
type GroupMappingRow = { groupId: string; roleId: string; group: string; source: string; role: string; members: number };
type ModelRow = { id: string; name: string; type: string; provider: string; endpoint: string | null; default: boolean; status: string; raw?: AIModelResponse };
type ModelDeleteDependency = { type: string; count: number };
type PromptRow = SystemPromptResponse;
type ModalState =
  | { type: "user"; user: UserRow }
  | { type: "role"; role?: RoleRow }
  | { type: "role-users"; role: RoleRow }
  | { type: "mapping"; role: RoleRow }
  | { type: "role-delete"; role: RoleRow }
  | { type: "model"; model?: ModelRow }
  | { type: "model-delete"; model: ModelRow }
  | { type: "api-key-create" }
  | { type: "api-key-manage"; client: IntegrationClientResponse }
  | { type: "confirm"; title: string; message: string; actionLabel: string; run: () => Promise<void> };

function emptyPermissionState(): PermissionState {
  return Object.fromEntries(permissionMenuRows.map((row) => [row.key, { view: false, create: false, edit: false, delete: false, execute: false }]));
}

function permissionStateFromResponse(response: PermissionMatrixResponse): PermissionState {
  const state = emptyPermissionState();
  for (const permission of response.permissions) {
    const key = `${permission.module_name}.${permission.function_name}`;
    state[key] = { view: permission.can_view, create: permission.can_create, edit: permission.can_edit, delete: permission.can_delete, execute: permission.can_execute };
  }
  return state;
}

function permissionPayload(role: RoleRow, state: PermissionState): PermissionMatrixResponse {
  return {
    lock_version: role.lockVersion,
    permissions: permissionMenuRows.map((row) => {
      const value = state[row.key] ?? emptyPermissionState()[row.key];
      const actionSet = new Set<PermissionAction>(row.actions);
      return { module_name: row.moduleName, function_name: row.functionName, can_view: actionSet.has("view") && value.view, can_create: actionSet.has("create") && value.create, can_edit: actionSet.has("edit") && value.edit, can_delete: actionSet.has("delete") && value.delete, can_execute: actionSet.has("execute") && value.execute };
    })
  };
}

function permissionActionEnabled(row: (typeof permissionMenuRows)[number], action: PermissionAction) {
  return (row.actions as readonly PermissionAction[]).includes(action);
}

function StateBadge({ children, tone = "green" }: { children: React.ReactNode; tone?: "green" | "gold" | "gray" | "coral" }) {
  return <span className={`system-state system-state-${tone}`}>{children}</span>;
}

function statusTone(status: string): "green" | "gold" | "gray" | "coral" {
  if (status === "healthy") return "green";
  if (status === "degraded") return "gold";
  if (status === "unavailable") return "coral";
  return "gray";
}

function breakGlassTone(status?: BreakGlassStatusResponse["status"]): "green" | "gold" | "gray" | "coral" {
  if (status === "configured_disabled") return "green";
  if (status === "attention_required") return "gold";
  if (status === "unavailable") return "coral";
  return "gray";
}

function evidenceText(value: boolean | null | undefined, t: (key: TranslationKey) => string) {
  if (value === true) return t("identityVerified");
  if (value === false) return t("identityNeedsAttention");
  return t("identityNotVerified");
}

function evidenceStateText(value: string | null | undefined, t: (key: TranslationKey) => string) {
  if (value === "configured") return t("identityVerified");
  if (value === "deployment_only") return t("identityDeploymentOnly");
  if (value === "missing") return t("identityNeedsAttention");
  return t("identityNotVerified");
}

function breakGlassNormalStateText(status: BreakGlassStatusResponse | null, t: (key: TranslationKey) => string) {
  if (!status) return t("identityNotVerified");
  return status.enabled === false ? t("identityDisabled") : t("identityNeedsAttention");
}

const identitySyncPhaseKeys = {
  queued: "identitySyncPhaseQueued",
  provider_discovery: "identitySyncPhaseProviderDiscovery",
  provider_user_sync: "identitySyncPhaseProviderUsers",
  provider_group_sync: "identitySyncPhaseProviderGroups",
  snapshot_fetch: "identitySyncPhaseSnapshot",
  reconciliation: "identitySyncPhaseReconciliation",
  completed: "identitySyncPhaseCompleted",
  failed: "identitySyncPhaseFailed"
} as const satisfies Record<string, TranslationKey>;

const identitySyncStatusKeys = {
  queued: "identitySyncProviderQueued",
  pending: "identitySyncProviderPending",
  running: "identitySyncProviderRunning",
  succeeded: "identitySyncProviderSucceeded",
  failed: "identitySyncProviderFailed",
  skipped: "identitySyncProviderSkipped",
  not_requested: "identitySyncProviderNotRequested"
} as const satisfies Record<string, TranslationKey>;

function identitySyncPhaseText(phase: string, t: (key: TranslationKey) => string) {
  return t(identitySyncPhaseKeys[phase as keyof typeof identitySyncPhaseKeys] ?? "identitySyncPhaseUnknown");
}

function identitySyncStatusText(status: string, t: (key: TranslationKey) => string) {
  return t(identitySyncStatusKeys[status as keyof typeof identitySyncStatusKeys] ?? "identitySyncProviderUnknown");
}

function identitySyncScopeText(scope: IdentitySyncRunResponse["requested_scope"], t: (key: TranslationKey) => string) {
  if (scope === "people") return t("identityPeopleOnly");
  if (scope === "groups") return t("identityGroupsOnly");
  return t("identityPeopleAndGroups");
}

function identitySyncProgressText(
  run: IdentitySyncRunResponse,
  t: (key: TranslationKey) => string,
  format: (key: TranslationKey, params: Record<string, string | number>) => string
) {
  const phase = identitySyncPhaseText(run.phase, t);
  const activeProvider = run.provider_results.find((provider) => provider.status === "running");
  if (!activeProvider) return format("identitySyncProgressPhase", { phase });
  const providerIndex = run.provider_results.findIndex((provider) => provider.id === activeProvider.id);
  return format("identitySyncProgressProvider", {
    phase,
    provider: activeProvider.provider_name,
    current: providerIndex + 1,
    total: run.provider_results.length
  });
}

function identitySyncErrorKey(errorCode: string | null): TranslationKey {
  if (errorCode === "identity_sync_queue_timeout") return "identitySyncQueueTimeout";
  if (errorCode === "identity_sync_heartbeat_timeout" || errorCode === "identity_sync_run_budget_insufficient") return "identitySyncRunTimeout";
  if (errorCode === "keycloak_group_mapper_missing") return "identitySyncGroupMapperMissing";
  if (errorCode === "keycloak_group_mapper_ambiguous") return "identitySyncGroupMapperAmbiguous";
  if (errorCode === "keycloak_ldap_group_path_mismatch") return "identitySyncGroupPathMismatch";
  if (errorCode === "keycloak_provider_timeout") return "identitySyncProviderTimeout";
  if (errorCode === "keycloak_provider_sync_failed") return "identitySyncProviderFailedMessage";
  if (errorCode === "keycloak_group_mapper_sync_failed") return "identitySyncGroupSyncFailed";
  if (errorCode?.startsWith("keycloak_")) return "identitySyncKeycloakUnavailable";
  return "identitySyncFailed";
}

function metricPairs(metrics: OperationComponentStatus["metrics"]) {
  return Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined).slice(0, 4);
}

function identitySettingsFromConfiguration(configuration: Record<string, unknown>): IdentitySettings {
  return {
    issuer: typeof configuration.issuer_url === "string" ? configuration.issuer_url : "",
    realm: typeof configuration.realm === "string" ? configuration.realm : "",
    clientId: typeof configuration.client_id === "string" ? configuration.client_id : "",
    audience: typeof configuration.audience === "string" ? configuration.audience : "",
    discoveryUrl: typeof configuration.discovery_url === "string" ? configuration.discovery_url : "",
    keycloakEnabled: configuration.enabled === true,
    syncEnabled: configuration.sync_enabled === true,
    syncScope: configuration.sync_scope === "people" || configuration.sync_scope === "groups" ? configuration.sync_scope : "people_and_groups",
    schedule: typeof configuration.sync_schedule === "string" ? configuration.sync_schedule : "",
    timezone: typeof configuration.timezone === "string" ? configuration.timezone : ""
  };
}

function SectionHeader({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <div className="system-section-header"><div><h2>{title}</h2><p>{description}</p></div>{action}</div>;
}

function EmptyInlineState({ children }: { children?: React.ReactNode }) {
  const { t } = useI18n();
  return <div className="empty-inline-state"><Info size={18} />{children ?? t("systemNoLiveData")}</div>;
}

function modelRow(model: AIModelResponse): ModelRow {
  return { id: model.id, name: model.name, type: model.model_type, provider: model.provider, endpoint: model.endpoint, default: model.is_default, status: model.is_active ? "active" : "inactive", raw: model };
}

const aiProviders = [
  { id: "OpenAI", label: "OpenAI" },
  { id: "Gemini", label: "Gemini" },
  { id: "Claude", label: "Claude / Anthropic" },
  { id: "Ollama", label: "Ollama" },
  { id: "vLLM", label: "vLLM" },
  { id: "Custom", label: "Custom / Generic HTTP" }
];

function normalizedProvider(provider?: string | null) {
  const found = aiProviders.find((item) => item.id.toLowerCase() === (provider ?? "").toLowerCase());
  if (found) return found.id;
  if ((provider ?? "").toLowerCase() === "anthropic") return "Claude";
  return provider ? "Custom" : "OpenAI";
}

function modelConfigValue(model: ModelRow | undefined, key: string, fallback = "") {
  const value = model?.raw?.config?.[key];
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? String(value) : fallback;
}

function pairedEmbeddingModelIds(model: ModelRow | undefined) {
  const value = model?.raw?.config?.paired_embedding_model_ids;
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function providerNeedsCredential(provider: string) {
  return provider === "OpenAI" || provider === "Gemini" || provider === "Claude";
}

function providerHelpKey(provider: string): TranslationKey {
  if (provider === "OpenAI") return "systemProviderHelpOpenAI";
  if (provider === "Gemini") return "systemProviderHelpGemini";
  if (provider === "Claude") return "systemProviderHelpClaude";
  if (provider === "Ollama") return "systemProviderHelpOllama";
  if (provider === "vLLM") return "systemProviderHelpVllm";
  return "systemProviderHelpCustom";
}

const secretConfigKeys = new Set(["api_key", "apikey", "secret", "password", "credential", "authorization", "access_token", "refresh_token", "bearer_token", "auth_token"]);

function containsSecretConfigKey(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => containsSecretConfigKey(item));
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(([key, item]) => {
    const normalizedKey = key.toLowerCase().replaceAll("-", "_");
    return secretConfigKeys.has(normalizedKey) || normalizedKey.endsWith("_secret") || normalizedKey.endsWith("_api_key") || containsSecretConfigKey(item);
  });
}

type SystemManagementWorkspaceProps = {
  initialTab?: SystemTabId;
  initialReauthResult?: IdentityReauthResult | null;
  invalidReauthResult?: boolean;
};

function replaceSystemRoute(tab: SystemTabId, reauth: IdentityReauthResult | null | undefined = undefined) {
  const nextUrl = systemRouteUrl(window.location.href, tab, reauth);
  const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextUrl !== currentUrl) window.history.replaceState(window.history.state, "", nextUrl);
}

export default function SystemManagementWorkspace({
  initialTab = "users",
  initialReauthResult = null,
  invalidReauthResult = false
}: SystemManagementWorkspaceProps) {
  const { locale, t, format, localize } = useI18n();
  const { apiFetch, can } = useAuth();
  const [activeTab, setActiveTab] = useState<TabId>(initialTab);
  const [selectedRole, setSelectedRole] = useState("");
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>({});
  const [permissionSaved, setPermissionSaved] = useState(true);
  const [liveUsers, setLiveUsers] = useState<UserRow[]>([]);
  const [liveRoles, setLiveRoles] = useState<RoleRow[]>([]);
  const [liveGroupMappings, setLiveGroupMappings] = useState<GroupMappingRow[]>([]);
  const [liveModels, setLiveModels] = useState<ModelRow[]>([]);
  const [modelTableRows, setModelTableRows] = useState<ModelRow[]>([]);
  const [modelTableTotal, setModelTableTotal] = useState(0);
  const [modelTablePage, setModelTablePage] = useState(1);
  const [modelTablePageSize, setModelTablePageSize] = useState(20);
  const [modelTableType, setModelTableType] = useState("all");
  const [modelTableLoading, setModelTableLoading] = useState(false);
  const [modelTableError, setModelTableError] = useState("");
  const [systemPrompts, setSystemPrompts] = useState<PromptRow[]>([]);
  const [liveProjects, setLiveProjects] = useState<ProjectResponse[]>([]);
  const [integrationClients, setIntegrationClients] = useState<IntegrationClientResponse[]>([]);
  const [apiKeyProjectDraft, setApiKeyProjectDraft] = useState<string[]>([]);
  const [apiKeyScopeDrafts, setApiKeyScopeDrafts] = useState<Record<string, string[]>>({});
  const [apiKeyOneTime, setApiKeyOneTime] = useState<{ name: string; key: string } | null>(null);
  const [selectedPromptId, setSelectedPromptId] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [promptDraftSourceVersion, setPromptDraftSourceVersion] = useState<number | null>(null);
  const [promptModelDraft, setPromptModelDraft] = useState("");
  const [promptMessage, setPromptMessage] = useState("");
  const [promptError, setPromptError] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);
  const [promptEditorPrompt, setPromptEditorPrompt] = useState<PromptRow | null>(null);
  const [externalGroups, setExternalGroups] = useState<ExternalGroupResponse[]>([]);
  const [syncRuns, setSyncRuns] = useState<IdentitySyncRunResponse[]>([]);
  const [directoryProviders, setDirectoryProviders] = useState<DirectoryProviderResponse[]>([]);
  const [directoryProviderError, setDirectoryProviderError] = useState("");
  const [directoryFilterDrafts, setDirectoryFilterDrafts] = useState<Record<string, string>>({});
  const [savingDirectoryProviderId, setSavingDirectoryProviderId] = useState<string | null>(null);
  const [identityConfigurationSource, setIdentityConfigurationSource] = useState<"deployment" | "database">("deployment");
  const [identitySecretConfigured, setIdentitySecretConfigured] = useState(false);
  const [identitySyncing, setIdentitySyncing] = useState(false);
  const [breakGlassStatus, setBreakGlassStatus] = useState<BreakGlassStatusResponse | null>(null);
  const [systemStatus, setSystemStatus] = useState<OperationsStatusResponse | null>(null);
  const [liveReady, setLiveReady] = useState(false);
  const [systemLoading, setSystemLoading] = useState(true);
  const [systemError, setSystemError] = useState<ApiError | Error | null>(null);
  const [actionMessage, setActionMessage] = useState("");
  const [modal, setModal] = useState<ModalState | null>(null);
  const [modalError, setModalError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modelDeleteConfirmation, setModelDeleteConfirmation] = useState("");
  const [modelDeleteDependencies, setModelDeleteDependencies] = useState<ModelDeleteDependency[]>([]);
  const [modelProviderDraft, setModelProviderDraft] = useState("OpenAI");
  const [modelTypeDraft, setModelTypeDraft] = useState("Chat");
  const [modelPairDraft, setModelPairDraft] = useState<string[]>([]);
  const [modelCredentialClearDraft, setModelCredentialClearDraft] = useState(false);
  const [modelCredentialClearConfirmation, setModelCredentialClearConfirmation] = useState("");
  const [userQuery, setUserQuery] = useState("");
  const [userSourceFilter, setUserSourceFilter] = useState("all");
  const [roleUsers, setRoleUsers] = useState<RoleUsersResponse | null>(null);
  const [roleUserDraftIds, setRoleUserDraftIds] = useState<string[]>([]);
  const [roleUserSearch, setRoleUserSearch] = useState("");
  const [rolesView, setRolesView] = useState<"local" | "ldap">("local");
  const [roleQuery, setRoleQuery] = useState("");
  const [roleStatusFilter, setRoleStatusFilter] = useState<RoleStatusFilter>("all");
  const [roleActionId, setRoleActionId] = useState<string | null>(null);
  const [roleDeleteConfirmation, setRoleDeleteConfirmation] = useState("");
  const [mappingGroupDraft, setMappingGroupDraft] = useState("");
  const canViewSystemManagement = can("Menu", "SystemManagement", "view");
  const canCreateSystemManagement = can("Menu", "SystemManagement", "create");
  const canEditSystemManagement = can("Menu", "SystemManagement", "edit");
  const canDeleteSystemManagement = can("Menu", "SystemManagement", "delete");
  const canEditPermissions = canEditSystemManagement;
  const canEditParameters = canEditSystemManagement;
  const canEditUsers = canEditSystemManagement;
  const canEditRoles = canEditSystemManagement;
  const canCreateRoles = canCreateSystemManagement;
  const canDeleteRoles = canDeleteSystemManagement;
  const canEditModels = canEditSystemManagement;
  const canCreateModels = canCreateSystemManagement;
  const canDeleteModels = canDeleteSystemManagement;
  const errorMessage = useCallback((error: ApiError | Error | null) => operationalErrorMessage(error, t, format), [format, t]);

  const [parameters, setParameters] = useState(defaultSystemParameters);
  const [savedParameters, setSavedParameters] = useState(defaultSystemParameters);
  const [parameterErrors, setParameterErrors] = useState(validateSystemParameters(defaultSystemParameters));
  const [parameterMessage, setParameterMessage] = useState("");
  const [identitySettings, setIdentitySettings] = useState(emptyIdentitySettings);
  const [savedIdentitySettings, setSavedIdentitySettings] = useState(emptyIdentitySettings);
  const [identityErrors, setIdentityErrors] = useState<ReturnType<typeof validateIdentitySettings>>({});
  const [identityUnlocked, setIdentityUnlocked] = useState(false);
  const [identityUnlockExpiresAt, setIdentityUnlockExpiresAt] = useState<number | null>(null);
  const [identityNow, setIdentityNow] = useState(() => Date.now());
  const [reauthOpen, setReauthOpen] = useState(false);
  const [identityReauthStatus, setIdentityReauthStatus] = useState<IdentityReauthStatus>("ready");
  const [identityReauthError, setIdentityReauthError] = useState("");
  const [identityMessage, setIdentityMessage] = useState("");
  const identityReauthCompletingRef = useRef(false);
  const identityReauthResultProcessedRef = useRef(false);
  const identityReauthTriggerRef = useRef<HTMLButtonElement | null>(null);
  const roleMenuTriggerRef = useRef<HTMLElement | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const modelTableRequestRef = useRef(0);
  const selectedRoleRecord = liveRoles.find((role) => role.id === selectedRole);
  const selectedRoleLockVersion = selectedRoleRecord?.lockVersion;
  const selectedRoleReadOnly = selectedRoleRecord?.isActive === false;
  const selectedRoleReady = selectedRoleLockVersion !== undefined;
  const localizedTabs = tabs.map((tab) => ({ ...tab, label: t(tab.labelKey as TranslationKey) }));
  const localizedStatus = (status: string) => {
    if (status === "active") return t("systemEnabled");
    if (status === "inactive") return t("systemDisabled");
    return status;
  };
  const localizedOperationStatus = (status: string) => {
    if (status === "healthy") return t("systemOpHealthy");
    if (status === "degraded") return t("systemOpDegraded");
    if (status === "unavailable") return t("systemOpUnavailable");
    if (status === "success") return t("systemSuccess");
    if (status === "failed") return t("systemFailed");
    if (status === "stale") return t("systemConnectionStale");
    return status;
  };
  const modelDeleteDependencyLabel = (type: string) => {
    if (type === "system_default") return t("systemModelDependencyDefault");
    if (type === "current_project_assignment") return t("systemModelDependencyProject");
    if (type === "running_ocr_pipeline") return t("systemModelDependencyPipeline");
    if (type === "active_chat_pairing") return t("systemModelDependencyPairing");
    if (type === "active_system_prompt") return t("systemModelDependencyPrompt");
    return type;
  };

  async function runModelConnectionTest(model: ModelRow) {
    setSystemError(null);
    try {
      const tested = await testModel(apiFetch, model.id);
      setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(tested) : item));
      setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(tested) : item));
      setActionMessage(format("systemModelTestSucceeded", { latency: tested.last_test_latency_ms ?? 0 }));
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }
  const localizedBreakGlassStatus = (status?: BreakGlassStatusResponse["status"]) => {
    if (status === "configured_disabled") return t("identityBreakGlassConfiguredDisabled");
    if (status === "attention_required") return t("identityNeedsAttention");
    if (status === "unavailable") return t("systemOpUnavailable");
    return t("systemNotConfigured");
  };
  const activeEmbeddingModels = liveModels.filter((model) => model.type === "Embedding" && model.status === "active");

  async function loadSystem() {
    if (!canViewSystemManagement) {
      setSystemLoading(false);
      return;
    }
    setSystemLoading(true);
    setSystemError(null);
    try {
      const [userRows, roleRows, modelRows, promptRows, projectRows, integrationRows, parameterPayload, identityPayload, directoryProviderResult, externalGroups, mappings, syncRunRows, breakGlassPayload, statusPayload] = await Promise.all([
        listUsers(apiFetch),
        listRoles(apiFetch),
        listModels(apiFetch),
        listSystemPrompts(apiFetch).catch(() => []),
        listProjects(apiFetch).catch(() => []),
        listIntegrationClients(apiFetch).catch(() => []),
        getSystemParameters(apiFetch),
        getIdentitySettings(apiFetch),
        listDirectoryProviders(apiFetch)
          .then((providers) => ({ providers, error: "" }))
          .catch((caught) => ({ providers: [] as DirectoryProviderResponse[], error: errorMessage(caught as ApiError | Error) })),
        listExternalGroups(apiFetch),
        listExternalGroupMappings(apiFetch),
        listIdentitySyncRuns(apiFetch).catch(() => []),
        getBreakGlassStatus(apiFetch).catch(() => null),
        getSystemStatus(apiFetch).catch(() => null)
      ]);
      setLiveUsers(userRows.map((user: UserSummary) => ({ id: user.id, name: user.display_name, email: user.email ?? "—", department: user.department ?? "—", source: user.auth_source, roles: user.knowledge_owner ? "Knowledge Owner" : "—", status: user.is_active ? "active" : "inactive", raw: user })));
      const roleUserResponses = await Promise.all(roleRows.map(async (role) => getRoleUsers(apiFetch, role.id).catch(() => ({ lock_version: role.lock_version, users: [] }))));
      setLiveRoles(roleRows.map((role: RoleResponse, index) => {
        const memberships = roleUserResponses[index]?.users ?? [];
        const mapping = mappings.find((item) => item.role_id === role.id);
        return { id: role.id, name: role.name, members: new Set(memberships.map((item) => item.user_id)).size, manualMembers: memberships.filter((item) => item.source === "manual").length, ldapMembers: memberships.filter((item) => item.source === "external_sync").length, breakGlassMembers: memberships.filter((item) => item.source === "break_glass").length, groups: mapping ? 1 : 0, mappingGroupId: mapping?.external_group_id ?? null, description: role.description, lockVersion: role.lock_version, isSystem: role.is_system, isActive: role.is_active };
      }));
      setSelectedRole((current) => roleRows[0] ? (roleRows.some((role) => role.id === current) ? current : roleRows[0].id) : "");
      const groupById = new Map(externalGroups.map((group) => [group.id, group]));
      const roleById = new Map(roleRows.map((role) => [role.id, role]));
      setExternalGroups(externalGroups);
      setLiveGroupMappings(mappings.map((mapping) => ({ groupId: mapping.external_group_id, roleId: mapping.role_id, group: groupById.get(mapping.external_group_id)?.path || groupById.get(mapping.external_group_id)?.group_name || mapping.external_group_id, source: groupById.get(mapping.external_group_id)?.identity_origin || "keycloak_local", role: roleById.get(mapping.role_id)?.name || mapping.role_id, members: groupById.get(mapping.external_group_id)?.member_count ?? 0 })));
      const nextModels = modelRows.map(modelRow);
      setLiveModels(nextModels);
      setSystemPrompts(promptRows);
      setLiveProjects(projectRows);
      setIntegrationClients(integrationRows);
      setApiKeyScopeDrafts(Object.fromEntries(integrationRows.map((client) => [client.id, client.project_ids])));
      setApiKeyProjectDraft((current) => current.filter((projectId) => projectRows.some((project) => project.id === projectId)));
      const nextPrompt = promptRows.find((prompt) => prompt.id === selectedPromptId) ?? promptRows[0];
      setSelectedPromptId(nextPrompt?.id ?? "");
      setPromptDraft(nextPrompt?.content ?? "");
      setPromptDraftSourceVersion(null);
      setPromptModelDraft(nextModels.find((model) => (model.type === "Chat" || model.type === "Judge") && !promptRows.some((prompt) => prompt.model_id === model.id))?.id ?? "");
      setSyncRuns(syncRunRows);
      setDirectoryProviders(directoryProviderResult.providers);
      setDirectoryProviderError(directoryProviderResult.error);
      setDirectoryFilterDrafts(Object.fromEntries(directoryProviderResult.providers.map((provider) => [provider.id, provider.custom_user_search_filter])));
      setBreakGlassStatus(breakGlassPayload);
      setSystemStatus(statusPayload);
      const liveParameters = { uploadLimitMb: parameterPayload.max_upload_size_mb, timezone: parameterPayload.default_timezone, stagingTtlDays: parameterPayload.staging_index_ttl_days, sessionDraftTtlMinutes: parameterPayload.session_expired_form_draft_ttl_minutes };
      setParameters(liveParameters); setSavedParameters(liveParameters); setParameterErrors(validateSystemParameters(liveParameters));
      const identityFromApi = identitySettingsFromConfiguration(identityPayload.configuration);
      setIdentitySettings(identityFromApi);
      setSavedIdentitySettings(identityFromApi);
      setIdentityErrors(validateIdentitySettings(identityFromApi));
      setIdentityConfigurationSource(identityPayload.configuration_source);
      setIdentitySecretConfigured(identityPayload.secret_configured);
      setLiveReady(true);
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    } finally {
      setSystemLoading(false);
    }
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
      setModelTableTotal(page.total);
    } catch (caught) {
      if (requestId === modelTableRequestRef.current) {
        setModelTableError(errorMessage(caught as ApiError | Error));
      }
    } finally {
      if (requestId === modelTableRequestRef.current) setModelTableLoading(false);
    }
  }, [apiFetch, canViewSystemManagement, errorMessage, modelTablePage, modelTablePageSize, modelTableType]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadSystem(); }, 0);
    return () => window.clearTimeout(timer);
  }, [canViewSystemManagement]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    replaceSystemRoute(initialTab, initialReauthResult);
  }, [initialReauthResult, initialTab]);

  useEffect(() => {
    if (activeTab !== "models" || !liveReady) return;
    const timer = window.setTimeout(() => { void refreshModelTable(); }, 0);
    return () => window.clearTimeout(timer);
  }, [activeTab, liveReady, refreshModelTable]);

  useEffect(() => {
    if (!liveReady || !selectedRole || !selectedRoleReady) return;
    getPermissions(apiFetch, selectedRole).then((response) => {
      setPermissions((current) => ({ ...current, [selectedRole]: permissionStateFromResponse(response) }));
      setLiveRoles((current) => current.map((role) => role.id === selectedRole ? { ...role, lockVersion: response.lock_version } : role));
      setPermissionSaved(true);
    }).catch((caught) => setSystemError(caught as ApiError | Error));
  }, [apiFetch, liveReady, selectedRole, selectedRoleReady, selectedRoleLockVersion]);

  useEffect(() => {
    if (!identityUnlockExpiresAt) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      setIdentityNow(now);
      if (now >= identityUnlockExpiresAt) {
        setIdentitySettings(savedIdentitySettings);
        setIdentityErrors({});
        setIdentityUnlocked(false);
        setIdentityUnlockExpiresAt(null);
        setIdentityMessage(t("identityFixtureExpired"));
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [identityUnlockExpiresAt, savedIdentitySettings, t]);

  useEffect(() => {
    const restore = (event: Event) => {
      const detail = (event as CustomEvent<{ formKey: string; payload: Partial<SystemParameterValues> }>).detail;
      if (detail?.formKey !== "system.parameters") return;
      const next = { ...parameters, ...detail.payload };
      setParameters(next);
      setParameterErrors(validateSystemParameters(next));
      setParameterMessage(t("systemParametersDraftRestored"));
    };
    window.addEventListener("nomosmart:restore-session-draft", restore);
    return () => window.removeEventListener("nomosmart:restore-session-draft", restore);
  }, [parameters, t]);

  const remainingIdentitySeconds = identityUnlockExpiresAt ? Math.max(0, Math.ceil((identityUnlockExpiresAt - identityNow) / 1000)) : 0;
  const remainingIdentityTime = `${String(Math.floor(remainingIdentitySeconds / 60)).padStart(2, "0")}:${String(remainingIdentitySeconds % 60).padStart(2, "0")}`;
  const identityReauthBusy = identityReauthStatus === "opening" || identityReauthStatus === "completing";
  const userRowName = (user: UserRow) => formatPersonName(user.raw ?? { display_name: user.name }, locale) || user.name;
  const filteredUsers = liveUsers.filter((user) => {
    const haystack = `${personNameSearchText(user.raw ?? { display_name: user.name })} ${user.email} ${user.department} ${user.source}`.toLowerCase();
    return (!userQuery.trim() || haystack.includes(userQuery.trim().toLowerCase())) && (userSourceFilter === "all" || user.source === userSourceFilter);
  });
  const normalizedRoleQuery = roleQuery.trim().toLowerCase();
  const filteredLocalRoles = liveRoles.filter((role) => {
    const matchesQuery = !normalizedRoleQuery || `${role.name} ${role.description ?? ""}`.toLowerCase().includes(normalizedRoleQuery);
    const matchesStatus = roleStatusFilter === "all"
      || (roleStatusFilter === "enabled" && role.isActive !== false)
      || (roleStatusFilter === "disabled" && role.isActive === false);
    return matchesQuery && matchesStatus;
  });
  const roleUserRows = roleUsers?.users ?? [];
  const originalManualRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "manual").map((row) => row.user_id));
  const externalRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "external_sync").map((row) => row.user_id));
  const breakGlassRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "break_glass").map((row) => row.user_id));
  const draftRoleUserIds = new Set(roleUserDraftIds);
  const activeRoleUserCandidates = liveUsers.filter((user) => user.status === "active");
  const roleUserSearchTerm = roleUserSearch.trim().toLowerCase();
  const roleUserSearchText = (user: UserRow) => [
    personNameSearchText(user.raw ?? { display_name: user.name }),
    user.email,
    user.department,
    user.source,
    user.id,
    user.raw?.employee_id,
    user.raw?.keycloak_user_id
  ].filter(Boolean).join(" ").toLowerCase();
  const filteredRoleUserCandidates = activeRoleUserCandidates.filter((user) => !roleUserSearchTerm || roleUserSearchText(user).includes(roleUserSearchTerm));
  const pendingAddUsers = activeRoleUserCandidates.filter((user) => draftRoleUserIds.has(user.id) && !originalManualRoleUserIds.has(user.id));
  const pendingRemoveUsers = liveUsers.filter((user) => originalManualRoleUserIds.has(user.id) && !draftRoleUserIds.has(user.id));
  const activeProjects = liveProjects.filter((project) => project.status === "active");
  const projectNameById = new Map(liveProjects.map((project) => [project.id, project.name]));
  const ldapGroups = externalGroups.filter((group) => group.identity_origin === "ldap");
  const mappingRole = modal?.type === "mapping" ? modal.role : null;
  const availableMappingGroups = ldapGroups.filter((group) => group.is_active && (!group.mapped_role_id || group.mapped_role_id === mappingRole?.id));
  const modelTableTotalPages = Math.max(1, Math.ceil(modelTableTotal / modelTablePageSize));
  const modelTableFirst = modelTableTotal ? (modelTablePage - 1) * modelTablePageSize + 1 : 0;
  const modelTableLast = Math.min(modelTablePage * modelTablePageSize, modelTableTotal);

  function activateTab(tab: TabId, focusIndex?: number) {
    if (identityReauthStatus === "completing") return;
    if (activeTab === "identity" && tab !== "identity" && identityUnlocked) void lockIdentitySettings();
    if (tab !== "apiKeys") setApiKeyOneTime(null);
    setActiveTab(tab);
    replaceSystemRoute(tab, null);
    if (focusIndex !== undefined) tabRefs.current[focusIndex]?.focus();
  }

  function selectTab(index: number) {
    const normalizedIndex = (index + localizedTabs.length) % localizedTabs.length;
    const next = localizedTabs[(index + localizedTabs.length) % localizedTabs.length];
    activateTab(next.id, normalizedIndex);
  }

  function handleTabKey(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowRight") { event.preventDefault(); selectTab(index + 1); }
    if (event.key === "ArrowLeft") { event.preventDefault(); selectTab(index - 1); }
    if (event.key === "Home") { event.preventDefault(); selectTab(0); }
    if (event.key === "End") { event.preventDefault(); selectTab(localizedTabs.length - 1); }
  }

  function togglePermission(key: string, action: PermissionAction) {
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

  function updateParameter<K extends keyof SystemParameterValues>(key: K, value: SystemParameterValues[K]) {
    const next = { ...parameters, [key]: value };
    setParameters(next);
    setParameterErrors(validateSystemParameters(next));
    setParameterMessage("");
  }

  async function saveParameters() {
    const errors = validateSystemParameters(parameters);
    setParameterErrors(errors);
    if (hasParameterErrors(errors)) return;
    try {
      const saved = await updateSystemParameters(apiFetch, { max_upload_size_mb: parameters.uploadLimitMb, default_timezone: parameters.timezone, staging_index_ttl_days: parameters.stagingTtlDays, session_expired_form_draft_ttl_minutes: parameters.sessionDraftTtlMinutes });
      const next = { uploadLimitMb: saved.max_upload_size_mb, timezone: saved.default_timezone, stagingTtlDays: saved.staging_index_ttl_days, sessionDraftTtlMinutes: saved.session_expired_form_draft_ttl_minutes };
      setSavedParameters(next);
      setParameters(next);
      setParameterMessage(t("systemParametersSaved"));
    } catch (caught) {
      setParameterMessage(errorMessage(caught as ApiError | Error));
    }
  }

  function restoreParameters() {
    setParameters(defaultSystemParameters);
    setParameterErrors({});
    setParameterMessage(t("systemParametersDefaultsRestored"));
  }

  async function savePermissions() {
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

  async function refreshRolesAndMappings() {
    const [roleRows, externalGroupRows, mappings] = await Promise.all([listRoles(apiFetch), listExternalGroups(apiFetch), listExternalGroupMappings(apiFetch)]);
    const roleUserResponses = await Promise.all(roleRows.map(async (role) => getRoleUsers(apiFetch, role.id).catch(() => ({ lock_version: role.lock_version, users: [] }))));
    setExternalGroups(externalGroupRows);
    setLiveRoles(roleRows.map((role, index) => {
      const memberships = roleUserResponses[index]?.users ?? [];
      const mapping = mappings.find((item) => item.role_id === role.id);
      return { id: role.id, name: role.name, members: new Set(memberships.map((item) => item.user_id)).size, manualMembers: memberships.filter((item) => item.source === "manual").length, ldapMembers: memberships.filter((item) => item.source === "external_sync").length, breakGlassMembers: memberships.filter((item) => item.source === "break_glass").length, groups: mapping ? 1 : 0, mappingGroupId: mapping?.external_group_id ?? null, description: role.description, lockVersion: role.lock_version, isSystem: role.is_system, isActive: role.is_active };
    }));
    setSelectedRole((current) => roleRows[0] ? (roleRows.some((role) => role.id === current) ? current : roleRows[0].id) : "");
    const groupById = new Map(externalGroupRows.map((group) => [group.id, group]));
    const roleById = new Map(roleRows.map((role) => [role.id, role]));
    setLiveGroupMappings(mappings.map((mapping) => ({ groupId: mapping.external_group_id, roleId: mapping.role_id, group: groupById.get(mapping.external_group_id)?.path || groupById.get(mapping.external_group_id)?.group_name || mapping.external_group_id, source: groupById.get(mapping.external_group_id)?.identity_origin || "keycloak_local", role: roleById.get(mapping.role_id)?.name || mapping.role_id, members: groupById.get(mapping.external_group_id)?.member_count ?? 0 })));
  }

  async function refreshIdentityData() {
    const userRows = await listUsers(apiFetch);
    await refreshRolesAndMappings();
    setLiveUsers(userRows.map((user: UserSummary) => ({ id: user.id, name: user.display_name, email: user.email ?? "—", department: user.department ?? "—", source: user.auth_source, roles: user.knowledge_owner ? "Knowledge Owner" : "—", status: user.is_active ? "active" : "inactive", raw: user })));
  }

  async function refreshModels() {
    const rows = await listModels(apiFetch);
    setLiveModels(rows.map(modelRow));
    await refreshModelTable();
  }

  async function refreshPrompts() {
    const rows = await listSystemPrompts(apiFetch);
    setSystemPrompts(rows);
    const nextPrompt = rows.find((prompt) => prompt.id === selectedPromptId) ?? rows[0];
    setSelectedPromptId(nextPrompt?.id ?? "");
    setPromptDraft(nextPrompt?.content ?? "");
    setPromptDraftSourceVersion(null);
    setPromptModelDraft((current) => current || liveModels.find((model) => (model.type === "Chat" || model.type === "Judge") && !rows.some((prompt) => prompt.model_id === model.id))?.id || "");
  }

  async function refreshSystemStatus() {
    try {
      setSystemStatus(await getSystemStatus(apiFetch));
    } catch (caught) {
      setSystemStatus(null);
      setSystemError(caught as ApiError | Error);
    }
  }

  async function refreshIntegrationClients() {
    const rows = await listIntegrationClients(apiFetch);
    setIntegrationClients(rows);
    setApiKeyScopeDrafts(Object.fromEntries(rows.map((client) => [client.id, client.project_ids])));
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

  function apiDateValue(formData: FormData, key: string) {
    const value = String(formData.get(key) || "").trim();
    return value ? new Date(value).toISOString() : null;
  }

  function apiDateInputValue(value: string | null) {
    return value ? value.slice(0, 16) : "";
  }

  function sameApiKeyScope(left: string[], right: string[]) {
    return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
  }

  function syncIntegrationClient(updated: IntegrationClientResponse) {
    setIntegrationClients((current) => current.map((item) => item.id === updated.id ? updated : item));
    setApiKeyScopeDrafts((current) => ({ ...current, [updated.id]: updated.project_ids }));
    setModal((current) => current?.type === "api-key-manage" && current.client.id === updated.id ? { ...current, client: updated } : current);
  }

  function openApiKeyCreateModal() {
    setApiKeyProjectDraft([]);
    setModalError("");
    setModal({ type: "api-key-create" });
  }

  function openApiKeyManageModal(client: IntegrationClientResponse) {
    setApiKeyScopeDrafts((current) => ({ ...current, [client.id]: client.project_ids }));
    setModalError("");
    setModal({ type: "api-key-manage", client });
  }

  async function submitApiKey(formData: FormData) {
    if (!apiKeyProjectDraft.length) {
      setModalError(t("systemApiKeyProjectRequired"));
      return;
    }
    setSubmitting(true); setSystemError(null); setModalError("");
    try {
      const created = await createIntegrationClient(apiFetch, {
        name: String(formData.get("name") || "").trim(),
        description: String(formData.get("description") || "").trim() || null,
        contact_name: String(formData.get("contact_name") || "").trim() || null,
        contact_email: String(formData.get("contact_email") || "").trim() || null,
        contact_department: String(formData.get("contact_department") || "").trim() || null,
        valid_from: apiDateValue(formData, "valid_from"),
        expires_at: apiDateValue(formData, "expires_at"),
        requests_per_minute: Number(formData.get("requests_per_minute") || 60),
        project_ids: apiKeyProjectDraft
      });
      setApiKeyOneTime({ name: created.name, key: created.api_key });
      setApiKeyProjectDraft([]);
      await refreshIntegrationClients();
      setModal(null);
      setActionMessage(t("systemApiKeyCreated"));
    } catch (caught) {
      setModalError(errorMessage(caught as ApiError | Error));
    } finally {
      setSubmitting(false);
    }
  }

  async function saveApiKeyManagement(client: IntegrationClientResponse, formData: FormData) {
    const projectIds = apiKeyScopeDrafts[client.id] ?? client.project_ids;
    if (!projectIds.length) {
      setModalError(t("systemApiKeyProjectRequired"));
      return;
    }
    setSubmitting(true); setSystemError(null); setModalError("");
    try {
      const updated = await updateIntegrationClient(apiFetch, client.id, {
        lock_version: client.lock_version,
        name: String(formData.get("name") || "").trim(),
        description: String(formData.get("description") || "").trim() || null,
        contact_name: String(formData.get("contact_name") || "").trim() || null,
        contact_email: String(formData.get("contact_email") || "").trim() || null,
        contact_department: String(formData.get("contact_department") || "").trim() || null,
        valid_from: apiDateValue(formData, "valid_from"),
        expires_at: apiDateValue(formData, "expires_at"),
        requests_per_minute: Number(formData.get("requests_per_minute") || 60)
      });
      const finalClient = sameApiKeyScope(projectIds, updated.project_ids)
        ? updated
        : await replaceIntegrationClientProjectScopes(apiFetch, client.id, { lock_version: updated.lock_version, project_ids: projectIds });
      syncIntegrationClient(finalClient);
      setModal(null);
      setActionMessage(t("systemApiKeyUpdated"));
    } catch (caught) {
      setModalError(errorMessage(caught as ApiError | Error));
    } finally {
      setSubmitting(false);
    }
  }

  async function saveApiKeyScope(client: IntegrationClientResponse) {
    const projectIds = apiKeyScopeDrafts[client.id] ?? [];
    if (!projectIds.length) {
      setActionMessage(t("systemApiKeyProjectRequired"));
      return;
    }
    try {
      const updated = await replaceIntegrationClientProjectScopes(apiFetch, client.id, { lock_version: client.lock_version, project_ids: projectIds });
      syncIntegrationClient(updated);
      setActionMessage(t("systemApiKeyScopeSaved"));
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }

  async function rotateApiKey(client: IntegrationClientResponse) {
    try {
      const rotated = await rotateIntegrationClientKey(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_rotate" });
      setApiKeyOneTime({ name: rotated.name, key: rotated.api_key });
      await refreshIntegrationClients();
      setModal(null);
      setActionMessage(t("systemApiKeyRotated"));
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }

  async function setApiKeyStatus(client: IntegrationClientResponse, active: boolean) {
    try {
      const updated = active
        ? await activateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_activate" })
        : await deactivateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_deactivate" });
      syncIntegrationClient(updated);
      setActionMessage(active ? t("systemApiKeyActivated") : t("systemApiKeyDeactivated"));
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }

  async function revokeApiKey(client: IntegrationClientResponse) {
    try {
      const updated = await revokeIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_revoke" });
      syncIntegrationClient(updated);
      setActionMessage(t("systemApiKeyRevoked"));
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
      throw caught;
    }
  }

  function apiKeyStatusLabel(client: IntegrationClientResponse) {
    if (client.effective_status === "expired") return t("systemApiKeyExpired");
    if (client.effective_status === "scheduled") return t("systemApiKeyScheduled");
    if (client.status === "revoked") return t("systemApiKeyRevokedStatus");
    return client.status === "active" ? t("systemEnabled") : t("systemDisabled");
  }

  function apiKeyStatusTone(client: IntegrationClientResponse): "green" | "gold" | "gray" | "coral" {
    if (client.status === "revoked") return "coral";
    if (client.effective_status === "expired" || client.effective_status === "scheduled") return "gold";
    return client.status === "active" ? "green" : "gray";
  }

  async function activateModel(model: ModelRow) {
    const updated = await updateModel(apiFetch, model.id, { is_active: true });
    setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setActionMessage(t("systemModelActivated"));
  }

  async function deactivateModelRow(model: ModelRow) {
    const updated = await updateModel(apiFetch, model.id, { is_active: false });
    setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setActionMessage(t("systemModelDeactivated"));
  }

  function openModelDeleteModal(model: ModelRow) {
    setModelDeleteConfirmation("");
    setModelDeleteDependencies([]);
    setModalError("");
    setModal({ type: "model-delete", model });
  }

  async function submitModelDelete(model: ModelRow) {
    if (!model.raw || modelDeleteConfirmation !== model.name) return;
    setSubmitting(true);
    setModalError("");
    setModelDeleteDependencies([]);
    try {
      await deleteModel(apiFetch, model.id, {
        confirmation_name: modelDeleteConfirmation,
        config_version: model.raw.config_version
      });
      await refreshModels();
      setActionMessage(t("systemModelDeleted"));
      setModal(null);
    } catch (caught) {
      const error = caught as ApiError | Error;
      const details = (error as ApiError).details as { dependencies?: ModelDeleteDependency[] } | undefined;
      if ((error as ApiError).status === 409 && Array.isArray(details?.dependencies)) {
        setModelDeleteDependencies(details.dependencies);
      }
      setModalError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  async function createGlobalPrompt(modelType: "Chat" | "Judge") {
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await createSystemPrompt(apiFetch, { prompt_scope: "global", model_type: modelType, content: "", is_active: false });
      await refreshPrompts();
      setSelectedPromptId(prompt.id);
      setPromptDraft(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptEditorPrompt(prompt);
      setPromptEditorOpen(true);
      setPromptMessage(t("systemPromptCreated"));
    } catch (caught) {
      setPromptError(errorMessage(caught as ApiError | Error));
    } finally {
      setPromptSaving(false);
    }
  }

  async function createModelPrompt() {
    const model = liveModels.find((item) => item.id === promptModelDraft);
    if (!model || (model.type !== "Chat" && model.type !== "Judge")) return;
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await createSystemPrompt(apiFetch, { prompt_scope: "model", model_type: model.type, model_id: model.id, content: "", is_active: false });
      await refreshPrompts();
      setSelectedPromptId(prompt.id);
      setPromptDraft(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptEditorPrompt(prompt);
      setPromptEditorOpen(true);
      setPromptMessage(t("systemPromptCreated"));
    } catch (caught) {
      setPromptError(errorMessage(caught as ApiError | Error));
    } finally {
      setPromptSaving(false);
    }
  }

  async function savePromptVersion() {
    const selected = systemPrompts.find((prompt) => prompt.id === selectedPromptId) ?? (promptEditorPrompt?.id === selectedPromptId ? promptEditorPrompt : null);
    if (!selected || promptDraft.length > 8000) return;
    if (promptDraft.trim().length === 0) {
      setPromptError(t("systemPromptBlankContentError"));
      return;
    }
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await addSystemPromptVersion(apiFetch, selected.id, { content: promptDraft, is_active: selected.is_active, change_reason: null });
      await refreshPrompts();
      setSelectedPromptId(prompt.id);
      setPromptDraft(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptEditorPrompt(prompt);
      setPromptMessage(t("systemPromptSaved"));
    } catch (caught) {
      setPromptError(errorMessage(caught as ApiError | Error));
    } finally {
      setPromptSaving(false);
    }
  }

  async function togglePromptActive(active: boolean) {
    const selected = systemPrompts.find((prompt) => prompt.id === selectedPromptId) ?? (promptEditorPrompt?.id === selectedPromptId ? promptEditorPrompt : null);
    if (!selected) return;
    if (active && selected.content.trim().length === 0) {
      setPromptError(t("systemPromptBlankContentError"));
      return;
    }
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await (active ? activateSystemPrompt(apiFetch, selected.id, selected.current_version_id) : deactivateSystemPrompt(apiFetch, selected.id));
      await refreshPrompts();
      setSelectedPromptId(prompt.id);
      setPromptDraft(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptEditorPrompt(prompt);
      setPromptMessage(active ? t("systemPromptActivated") : t("systemPromptDeactivated"));
    } catch (caught) {
      setPromptError(errorMessage(caught as ApiError | Error));
    } finally {
      setPromptSaving(false);
    }
  }

  function selectPrompt(prompt: PromptRow) {
    setSelectedPromptId(prompt.id);
    setPromptDraft(prompt.content);
    setPromptDraftSourceVersion(null);
    setPromptError("");
    setPromptMessage("");
    setPromptEditorPrompt(prompt);
    setPromptEditorOpen(true);
  }

  function loadPromptVersionDraft(version: PromptRow["versions"][number]) {
    setPromptDraft(version.content);
    setPromptDraftSourceVersion(version.version_number);
    setPromptMessage(format("systemPromptLoadedVersionDraft", { version: version.version_number }));
  }

  async function submitRole(formData: FormData) {
    setSubmitting(true); setModalError("");
    try {
      const name = modal?.type === "role" && modal.role?.isSystem ? modal.role.name : String(formData.get("name") || "").trim();
      const description = String(formData.get("description") || "").trim() || null;
      if (modal?.type === "role" && modal.role) await updateRole(apiFetch, modal.role.id, { lock_version: modal.role.lockVersion, name, description });
      else await createRole(apiFetch, { name, description });
      await refreshRolesAndMappings();
      setModal(null); setActionMessage(t("systemRoleDataUpdated"));
    } catch (caught) { setModalError(errorMessage(caught as ApiError | Error)); }
    finally { setSubmitting(false); }
  }

  async function openRoleUsers(role: RoleRow) {
    setModalError("");
    const response = await getRoleUsers(apiFetch, role.id);
    setRoleUsers(response);
    setRoleUserDraftIds(response.users.filter((row) => row.source === "manual").map((row) => row.user_id));
    setRoleUserSearch("");
    setModal({ type: "role-users", role });
  }

  function toggleRoleUserDraft(userId: string, checked: boolean) {
    setRoleUserDraftIds((current) => checked ? [...new Set([...current, userId])] : current.filter((id) => id !== userId));
  }

  function roleUserStatusLabels(user: UserRow) {
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
    const parts = [
      user.email,
      user.raw?.employee_id ? format("systemEmployeeIdValue", { id: user.raw.employee_id }) : null,
      user.source
    ].filter(Boolean);
    return parts.join(" · ");
  }

  async function saveRoleUsers() {
    if (modal?.type !== "role-users" || modal.role.isActive === false || !roleUsers) return;
    setSubmitting(true); setModalError("");
    try {
      const response = await replaceRoleUsers(apiFetch, modal.role.id, { lock_version: roleUsers.lock_version, user_ids: roleUserDraftIds });
      setRoleUsers(response);
      setRoleUserDraftIds(response.users.filter((row) => row.source === "manual").map((row) => row.user_id));
      await refreshRolesAndMappings();
      setModal(null); setActionMessage(t("systemManualRoleUsersSaved"));
    } catch (caught) { setModalError(errorMessage(caught as ApiError | Error)); }
    finally { setSubmitting(false); }
  }

  function openRoleMapping(role: RoleRow) {
    setMappingGroupDraft(role.mappingGroupId ?? "");
    setModalError("");
    setModal({ type: "mapping", role });
  }

  async function saveRoleMapping() {
    if (modal?.type !== "mapping" || modal.role.isActive === false) return;
    setSubmitting(true); setModalError("");
    try {
      await setRoleExternalGroupMapping(apiFetch, modal.role.id, { external_group_id: mappingGroupDraft || null, lock_version: modal.role.lockVersion });
      await refreshRolesAndMappings();
      setModal(null); setActionMessage(t("systemMappingsSaved"));
    } catch (caught) {
      if ((caught as ApiError).status === 409) {
        await refreshRolesAndMappings();
        setModal(null);
        setSystemError(caught as ApiError);
      } else {
        setModalError(errorMessage(caught as ApiError | Error));
      }
    }
    finally { setSubmitting(false); }
  }

  async function changeRoleLifecycle(role: RoleRow, isActive: boolean) {
    setRoleActionId(role.id);
    setSystemError(null);
    try {
      const updated = await updateRole(apiFetch, role.id, { lock_version: role.lockVersion, is_active: isActive });
      await refreshRolesAndMappings();
      setActionMessage(format(isActive ? "systemRoleActivated" : "systemRoleDisabledMessage", { name: updated.name }));
    } finally {
      setRoleActionId(null);
    }
  }

  function openRoleDelete(role: RoleRow, trigger: HTMLElement) {
    roleMenuTriggerRef.current = trigger.closest("details")?.querySelector("summary") ?? trigger;
    setRoleDeleteConfirmation("");
    setModalError("");
    setModal({ type: "role-delete", role });
  }

  async function submitRoleDelete(role: RoleRow) {
    setSubmitting(true);
    setModalError("");
    try {
      await deleteRole(apiFetch, role.id, role.lockVersion, roleDeleteConfirmation);
      await refreshRolesAndMappings();
      setModal(null);
      setActionMessage(format("systemRoleDeleted", { name: role.name }));
    } catch (caught) {
      setModalError(errorMessage(caught as ApiError | Error));
    } finally {
      setSubmitting(false);
    }
  }

  function closeModal() {
    const restoreTarget = modal?.type === "role-delete" ? roleMenuTriggerRef.current : null;
    setModal(null);
    if (restoreTarget) window.requestAnimationFrame(() => restoreTarget.focus());
  }

  async function submitUser(formData: FormData) {
    if (modal?.type !== "user") return;
    setSubmitting(true); setModalError("");
    try {
      const updated = await updateUser(apiFetch, modal.user.id, {
        knowledge_owner: formData.get("knowledge_owner") === "on",
        manager_delegate_user_id: String(formData.get("manager_delegate_user_id") || "") || null,
        system_notes: String(formData.get("system_notes") || "")
      });
      setLiveUsers((current) => current.map((user) => user.id === updated.id ? { ...user, roles: updated.knowledge_owner ? "Knowledge Owner" : "—", status: updated.is_active ? "active" : "inactive", raw: updated } : user));
      setModal(null); setActionMessage(t("systemUserLocalFieldsSaved"));
    } catch (caught) { setModalError(errorMessage(caught as ApiError | Error)); }
    finally { setSubmitting(false); }
  }

  async function toggleUser(user: UserRow) {
    const next = user.status !== "active";
    const updated = await updateUserStatus(apiFetch, user.id, next);
    setLiveUsers((current) => current.map((item) => item.id === user.id ? { ...item, status: updated.is_active ? "active" : "inactive", raw: updated } : item));
    setActionMessage(format("systemUserToggled", { action: next ? t("systemEnabled") : t("systemDisabled") }));
  }

  function openModelModal(model?: ModelRow) {
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
    setSubmitting(true); setModalError("");
    try {
      const configText = String(formData.get("config_advanced") || "{}");
      let config: Record<string, unknown> = {};
      try { config = JSON.parse(configText) as Record<string, unknown>; } catch { throw new Error(t("systemConfigJsonInvalid")); }
      if (containsSecretConfigKey(config)) throw new Error(t("systemConfigJsonNoSecrets"));
      const provider = String(formData.get("provider") || "OpenAI");
      const modelType = String(formData.get("model_type") || "Chat");
      const modelName = String(formData.get("model_name") || "").trim();
      const baseUrl = String(formData.get("base_url") || "").trim();
      const endpoint = String(formData.get("endpoint") || baseUrl || "").trim();
      const pairedIds = formData.getAll("paired_embedding_model_ids").map((value) => String(value)).filter(Boolean);
      if (modelType === "Chat" && pairedIds.length === 0) throw new Error(t("systemChatModelPairRequired"));
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
      const pricingKeys = ["input_cost_per_million_tokens", "output_cost_per_million_tokens", "embedding_cost_per_million_tokens", "ocr_cost_per_page", "ocr_cost_per_image"];
      pricingKeys.forEach((key) => delete config[key]);
      let hasPricing = false;
      for (const key of pricingKeys) {
        const value = String(formData.get(key) ?? "").trim();
        if (!value) continue;
        const price = Number(value);
        if (!Number.isFinite(price) || price < 0) throw new Error(t("systemModelPricingNonNegative"));
        config[key] = value;
        hasPricing = true;
      }
      const costCurrency = String(formData.get("cost_currency") || "").trim().toUpperCase();
      if (hasPricing && !costCurrency) throw new Error(t("systemModelPricingCurrencyRequired"));
      if (costCurrency) config.cost_currency = costCurrency;
      else delete config.cost_currency;
      if (provider === "Custom") {
        const headersText = String(formData.get("headers_json") || "{}");
        let headers: Record<string, unknown> = {};
        try { headers = JSON.parse(headersText) as Record<string, unknown>; } catch { throw new Error(t("systemHeadersJsonInvalid")); }
        if (containsSecretConfigKey(headers)) throw new Error(t("systemHeadersJsonNoSecrets"));
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
          if (modelCredentialClearConfirmation !== modal.model.name) throw new Error(t("systemModelCredentialClearConfirmationMismatch"));
          if (apiKey || secretRef) throw new Error(t("systemModelCredentialActionAmbiguous"));
          payload.clear_credential = true;
          payload.credential_clear_confirmation = modelCredentialClearConfirmation;
        } else if (apiKey) {
          payload.api_key = apiKey;
          if (secretRef && secretRef !== (modal.model.raw?.api_key_secret_ref ?? "")) payload.api_key_secret_ref = secretRef;
        } else if (secretRef && secretRef !== (modal.model.raw?.api_key_secret_ref ?? "")) {
          payload.api_key_secret_ref = secretRef;
        }
        await updateModel(apiFetch, modal.model.id, payload);
      } else {
        if (apiKey) payload.api_key = apiKey;
        if (secretRef) payload.api_key_secret_ref = secretRef;
        await createModel(apiFetch, payload as AIModelPayload & { model_type: string });
      }
      await refreshModels();
      setModal(null); setActionMessage(t("systemModelSettingsUpdated"));
    } catch (caught) { setModalError(errorMessage(caught as ApiError | Error)); }
    finally { setSubmitting(false); }
  }

  function identityCandidate(): IdentitySettingsCandidate {
    const issuer = identitySettings.issuer.replace(/\/+$/, "");
    return {
      issuer_url: issuer,
      realm: identitySettings.realm,
      client_id: identitySettings.clientId,
      audience: identitySettings.audience,
      discovery_url: identitySettings.discoveryUrl,
      jwks_url: `${issuer}/protocol/openid-connect/certs`,
      enabled: identitySettings.keycloakEnabled,
      sync_enabled: identitySettings.syncEnabled,
      sync_scope: identitySettings.syncScope,
      sync_schedule: identitySettings.schedule,
      timezone: identitySettings.timezone
    };
  }

  function updateIdentity<K extends keyof IdentitySettings>(key: K, value: IdentitySettings[K]) {
    const next = { ...identitySettings, [key]: value };
    setIdentitySettings(next);
    setIdentityErrors(validateIdentitySettings(next));
    setIdentityMessage("");
  }

  function identityErrorMessage(field: IdentityValidationField) {
    return identityErrors[field] ? t(identityValidationMessageKeys[field]) : "";
  }

  async function lockIdentitySettings() {
    if (identityUnlocked) await lockIdentitySettingsApi(apiFetch).catch(() => undefined);
    setIdentitySettings(savedIdentitySettings);
    setIdentityErrors({});
    setIdentityUnlocked(false);
    setIdentityUnlockExpiresAt(null);
    setIdentityMessage(t("identityLockCancelled"));
  }

  async function saveIdentitySettings() {
    const errors = validateIdentitySettings(identitySettings);
    setIdentityErrors(errors);
    if (Object.keys(errors).length) return;
    setSubmitting(true);
    try {
      await validateIdentitySettingsCandidate(apiFetch, identityCandidate());
      const response = await activateIdentitySettings(apiFetch, identityCandidate());
      const saved = identitySettingsFromConfiguration(response.configuration);
      setSavedIdentitySettings(saved);
      setIdentitySettings(saved);
      setIdentityErrors(validateIdentitySettings(saved));
      setIdentityConfigurationSource(response.configuration_source);
      setIdentitySecretConfigured(response.secret_configured);
      setIdentityUnlocked(false);
      setIdentityUnlockExpiresAt(null);
      setIdentityMessage(t("identitySettingsSavedAndLocked"));
    } catch (caught) {
      setIdentityMessage(errorMessage(caught as ApiError | Error));
    } finally {
      setSubmitting(false);
    }
  }

  const restoreIdentityReauthFocus = useCallback(() => {
    window.setTimeout(() => identityReauthTriggerRef.current?.focus(), 0);
  }, []);

  const dismissIdentityReauth = useCallback(() => {
    identityReauthCompletingRef.current = false;
    setIdentityReauthStatus("ready");
    setIdentityReauthError("");
    setReauthOpen(false);
    restoreIdentityReauthFocus();
  }, [restoreIdentityReauthFocus]);

  const clearIdentityReauthResult = useCallback(() => {
    replaceSystemRoute("identity", null);
  }, []);

  const finishIdentityReauthentication = useCallback(async () => {
    if (identityReauthCompletingRef.current) return;
    identityReauthCompletingRef.current = true;
    setIdentityReauthStatus("completing");
    setIdentityReauthError("");
    try {
      const grant = await completeIdentityReauth(apiFetch);
      const expiresAt = Date.parse(grant.expires_at);
      const now = Date.now();
      clearIdentityReauthResult();
      setIdentityUnlocked(true);
      setIdentityNow(now);
      setIdentityUnlockExpiresAt(Number.isFinite(expiresAt) ? expiresAt : now + identityUnlockDurationMs);
      setIdentityMessage(t("identityUnlockGrantIssued"));
      setReauthOpen(false);
      setIdentityReauthStatus("ready");
      restoreIdentityReauthFocus();
    } catch (caught) {
      clearIdentityReauthResult();
      setIdentityUnlocked(false);
      setIdentityUnlockExpiresAt(null);
      setReauthOpen(true);
      setIdentityReauthStatus("error");
      setIdentityReauthError(errorMessage(caught as ApiError | Error));
    } finally {
      identityReauthCompletingRef.current = false;
    }
  }, [apiFetch, clearIdentityReauthResult, errorMessage, restoreIdentityReauthFocus, t]);

  const processIdentityReauthResult = useCallback((result: IdentityReauthResult | null, invalid = false) => {
    if (identityReauthResultProcessedRef.current) return;
    identityReauthResultProcessedRef.current = true;
    setActiveTab("identity");
    if (result === "success") {
      setReauthOpen(true);
      void finishIdentityReauthentication();
      return;
    }
    clearIdentityReauthResult();
    setIdentityUnlocked(false);
    setIdentityUnlockExpiresAt(null);
    setReauthOpen(true);
    setIdentityReauthStatus("error");
    setIdentityReauthError(t(
      result === "cancelled"
        ? "identityReauthCancelled"
        : result === "pending"
          ? "identityReauthInterrupted"
          : invalid
            ? "identityReauthInvalidResult"
            : "identityReauthFailed"
    ));
  }, [clearIdentityReauthResult, finishIdentityReauthentication, t]);

  useEffect(() => {
    if (!initialReauthResult && !invalidReauthResult) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) processIdentityReauthResult(initialReauthResult, invalidReauthResult);
    });
    return () => {
      cancelled = true;
    };
  }, [initialReauthResult, invalidReauthResult, processIdentityReauthResult]);

  useEffect(() => {
    const handlePageShow = () => {
      const url = new URL(window.location.href);
      const values = url.searchParams.getAll("reauth");
      if (!values.length) return;
      const result = values.length === 1 ? parseIdentityReauthResult(values[0]) : null;
      processIdentityReauthResult(result, result === null);
    };
    window.addEventListener("pageshow", handlePageShow);
    return () => window.removeEventListener("pageshow", handlePageShow);
  }, [processIdentityReauthResult]);

  function openIdentityReauthDialog() {
    if (!canEditSystemManagement) return;
    setIdentityReauthStatus("ready");
    setIdentityReauthError("");
    setIdentityMessage("");
    setReauthOpen(true);
  }

  async function beginIdentityReauthentication() {
    if (!canEditSystemManagement || identityReauthStatus === "opening" || identityReauthStatus === "completing") return;
    identityReauthResultProcessedRef.current = false;
    setIdentityReauthError("");
    setIdentityReauthStatus("opening");
    try {
      const flow = await startIdentityReauth(apiFetch);
      replaceSystemRoute("identity", "pending");
      window.location.assign(flow.authorization_url);
    } catch (caught) {
      setIdentityReauthStatus("error");
      setIdentityReauthError(errorMessage(caught as ApiError | Error));
    }
  }

  async function runIdentitySync() {
    if (identitySyncing || syncRuns.some((run) => run.status === "queued" || run.status === "running")) return;
    setIdentitySyncing(true);
    setIdentityMessage(t("identitySyncInProgress"));
    try {
      let run = await queueIdentitySync(apiFetch);
      setSyncRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      while (run.status === "queued" || run.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        run = await getIdentitySyncRun(apiFetch, run.id);
        setSyncRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      }
      if (run.status === "succeeded") {
        setIdentityMessage(t("identitySyncSucceeded"));
        try {
          await refreshIdentityData();
        } catch {
          setIdentityMessage(t("identitySyncSucceededRefreshFailed"));
        }
      } else {
        setIdentityMessage(t(identitySyncErrorKey(run.error_code)));
      }
    } catch (caught) {
      const error = caught as ApiError | Error;
      if ("code" in error && error.code === "identity_sync_worker_unavailable") setIdentityMessage(t("identitySyncWorkerUnavailable"));
      else if ("code" in error && error.code === "identity_sync_already_running") setIdentityMessage(t("identitySyncAlreadyRunning"));
      else setIdentityMessage(errorMessage(error));
    } finally {
      setIdentitySyncing(false);
    }
  }

  async function saveDirectoryFilter(provider: DirectoryProviderResponse) {
    if (!identityUnlocked || savingDirectoryProviderId) return;
    setSavingDirectoryProviderId(provider.id);
    setIdentityMessage("");
    try {
      const updated = await updateDirectoryProviderFilter(apiFetch, provider.id, {
        custom_user_search_filter: directoryFilterDrafts[provider.id] ?? "",
        config_hash: provider.config_hash
      });
      setDirectoryProviders((current) => current.map((item) => item.id === updated.id ? updated : item));
      setDirectoryFilterDrafts((current) => ({ ...current, [updated.id]: updated.custom_user_search_filter }));
      setIdentityMessage(t("identityDirectoryFilterSaved"));
    } catch (caught) {
      const error = caught as ApiError | Error;
      if ("code" in error && error.code === "directory_provider_conflict") setIdentityMessage(t("identityDirectoryFilterConflict"));
      else if ("code" in error && (error.code === "directory_filter_invalid" || error.code === "directory_filter_too_long")) setIdentityMessage(t("identityDirectoryFilterInvalid"));
      else setIdentityMessage(errorMessage(error));
    } finally {
      setSavingDirectoryProviderId(null);
    }
  }

  const identityWorkerAvailable = systemStatus?.worker.metrics.worker_available === true;
  const identityProviderComponent = systemStatus?.dependencies.find((component) => component.name.includes("keycloak") || component.name.includes("oidc"));
  const identityProviderStatus = identityProviderComponent?.status ?? "unknown";

  const selectedPrompt = systemPrompts.find((prompt) => prompt.id === selectedPromptId);
  const activePromptEditor = promptEditorOpen ? (selectedPrompt ?? promptEditorPrompt) : null;
  const promptModels = liveModels.filter((model) => model.type === "Chat" || model.type === "Judge");
  const promptModelOptions = promptModels.filter((model) => !systemPrompts.some((prompt) => prompt.model_id === model.id));
  const globalChatPrompt = systemPrompts.find((prompt) => prompt.prompt_scope === "global" && prompt.model_type === "Chat");
  const globalJudgePrompt = systemPrompts.find((prompt) => prompt.prompt_scope === "global" && prompt.model_type === "Judge");
  const modelSpecificPrompts = systemPrompts.filter((prompt) => prompt.prompt_scope === "model");
  const promptLabel = (prompt: PromptRow) => prompt.prompt_scope === "global" ? format("systemPromptGlobalLabel", { type: prompt.model_type }) : format("systemPromptModelLabel", { model: liveModels.find((model) => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—", type: prompt.model_type });
  const promptScopeLabel = (prompt: PromptRow) => prompt.prompt_scope === "global" ? t("systemPromptScopeGlobal") : t("systemPromptScopeModel");

  function renderPromptEditor(prompt: PromptRow) {
    const model = prompt.model_id ? liveModels.find((item) => item.id === prompt.model_id) : null;
    const promptDraftBlank = promptDraft.trim().length === 0;
    const currentPromptBlank = prompt.content.trim().length === 0;
    return (
      <div className="system-prompt-editor system-crud-form">
        {model ? <div className="system-prompt-target"><Bot size={16} /><span>{t("systemPromptTargetModel")}</span><strong>{model.name}</strong><small>{model.provider}</small></div> : null}
        {promptDraftSourceVersion ? <div className="system-prompt-layer-note"><Info size={17} /><div><strong>{format("systemPromptLoadedVersionDraft", { version: promptDraftSourceVersion })}</strong><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div> : null}
        <div className="identity-form-grid">
          <label className="identity-wide-field"><span>{t("systemPromptContent")}</span><textarea maxLength={8000} onChange={(event) => setPromptDraft(event.target.value)} rows={12} value={promptDraft} /><small>{format("systemPromptLength", { count: promptDraft.length, max: 8000 })}{promptDraftBlank ? ` · ${t("systemPromptBlankContentError")}` : ""}</small></label>
        </div>
        <div className="system-prompt-history-heading"><div><h3>{t("systemPromptVersionHistory")}</h3><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div>
        <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemVersion")}</th><th>{t("systemLength")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemTime")}</th><th>{t("systemAction")}</th></tr></thead><tbody>{prompt.versions.map((version) => <tr className={promptDraftSourceVersion === version.version_number ? "selected-row" : ""} key={version.id}><td><button className="system-version-load-button" onClick={() => loadPromptVersionDraft(version)} type="button">{format("systemVersionValue", { version: version.version_number })}</button></td><td>{version.content.length}</td><td><StateBadge tone={version.is_active ? "green" : "gray"}>{version.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></td><td>{version.created_at.slice(0, 16).replace("T", " ")}</td><td><button className="icon-text-button" onClick={() => loadPromptVersionDraft(version)} type="button">{t("systemPromptLoadVersionDraft")}</button></td></tr>)}</tbody></table></div>
        <footer><button className="action-button secondary" disabled={!canEditModels || promptSaving || prompt.is_active || currentPromptBlank} onClick={() => { void togglePromptActive(true); }} type="button"><Check size={16} />{t("systemEnable")}</button><button className="action-button secondary" disabled={!canEditModels || promptSaving || !prompt.is_active} onClick={() => { void togglePromptActive(false); }} type="button"><X size={16} />{t("systemDisable")}</button><button className="action-button" disabled={!canEditModels || promptSaving || promptDraftBlank || promptDraft.length > 8000} onClick={() => { void savePromptVersion(); }} type="button"><Save size={16} />{t("systemPromptSaveVersion")}</button></footer>
      </div>
    );
  }

  function renderLocalRoleCard(role: RoleRow) {
    const isActive = role.isActive !== false;
    const isBusy = roleActionId === role.id;
    const mappedGroup = externalGroups.find((group) => group.id === role.mappingGroupId);
    const mappedGroupName = mappedGroup?.path || mappedGroup?.group_name || t("systemNoMapping");
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
                disabled={role.isSystem || !canEditRoles || isBusy}
                onClick={() => {
                  if (isActive) {
                    setModal({
                      type: "confirm",
                      title: t("systemDisableRoleTitle"),
                      message: format("systemDisableRoleHelp", { name: role.name }),
                      actionLabel: t("systemDisable"),
                      run: () => changeRoleLifecycle(role, false)
                    });
                  } else {
                    void changeRoleLifecycle(role, true).catch((caught) => setSystemError(caught as ApiError | Error));
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
            <dd><span>{format("systemRoleManualMembers", { count: role.manualMembers })}</span><span>{format("systemRoleLdapMembers", { count: role.ldapMembers })}</span>{role.breakGlassMembers ? <span>{format("systemRoleBreakGlassMembers", { count: role.breakGlassMembers })}</span> : null}</dd>
          </div>
        </dl>

        {!isActive ? <div className="system-role-readonly-note"><LockKeyhole size={14} /><span>{t("systemRoleReadOnlyHelp")}</span></div> : null}

        <footer className="system-card-actions">
          <button className="icon-text-button" disabled={isActive && !canEditRoles} onClick={() => setModal({ type: "role", role })} type="button">{isActive ? <Pencil size={15} /> : <Eye size={15} />}{isActive ? t("systemEdit") : t("systemRoleDetails")}</button>
          <button className="icon-text-button" onClick={() => { void openRoleUsers(role).catch((caught) => setSystemError(caught as ApiError | Error)); }} type="button"><UsersRound size={15} />{t("systemRoleUsers")}</button>
          <button className="icon-text-button" onClick={() => openRoleMapping(role)} type="button">{role.mappingGroupId ? <Unlink size={15} /> : <Link2 size={15} />}{mappingIsEditable ? (role.mappingGroupId ? t("systemChangeOrRemoveMapping") : t("systemSetMapping")) : t("systemViewMapping")}</button>
        </footer>

        {isBusy ? <div className="system-role-card-loading" role="status"><LoaderCircle className="spin" size={18} /><span>{t("systemRoleUpdating")}</span></div> : null}
      </article>
    );
  }

  if (!canViewSystemManagement) {
    return <ForbiddenState />;
  }

  const activeIdentityRun = syncRuns.find((run) => run.status === "queued" || run.status === "running");
  const visibleIdentityMessage = activeIdentityRun
    ? identitySyncProgressText(activeIdentityRun, t, format)
    : identityMessage;

  return (
    <section className="system-workspace">
      {systemLoading ? <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("loadingData")}</strong><span>{t("systemLoadingBackend")}</span></div></div> : null}
      {systemError ? <div className="error-summary" role="alert"><strong>{errorMessage(systemError)}</strong><button className="text-link" onClick={loadSystem} type="button">{t("retry")}</button></div> : null}
      {actionMessage ? <div className="fixture-banner"><Check size={17} /><div><strong>{t("liveData")}</strong><span>{localize(actionMessage)}</span></div></div> : null}
      <div className="system-overview" aria-label={t("systemOverviewAria")}>
        <div><span className="overview-icon"><UsersRound size={18} /></span><div><small>{t("systemSyncedUsers")}</small><strong>{liveUsers.length}</strong></div><StateBadge>{t("liveData")}</StateBadge></div>
        <div><span className="overview-icon"><ShieldCheck size={18} /></span><div><small>{t("systemRoleCount")}</small><strong>{liveRoles.length}</strong></div><span className="overview-helper">{format("systemExternalGroupMappings", { count: liveGroupMappings.length })}</span></div>
        <div><span className="overview-icon"><Bot size={18} /></span><div><small>{t("systemActiveModels")}</small><strong>{liveModels.filter((model) => model.status === "active").length}</strong></div><span className="overview-helper">{format("systemDefaultModels", { count: liveModels.filter((model) => model.default).length })}</span></div>
        <div><span className="overview-icon"><Activity size={18} /></span><div><small>{t("systemIdentitySync")}</small><strong>{syncRuns[0]?.status ?? "—"}</strong></div><span className="overview-helper">{syncRuns[0]?.started_at?.slice(0, 16).replace("T", " ") ?? t("systemNoLiveDataShort")}</span></div>
      </div>

      <div className="system-tab-shell">
        <div aria-label={t("systemTabsAria")} className="system-tabs" role="tablist">
          {localizedTabs.map((tab, index) => { const Icon = tab.icon; return <button aria-controls={`system-panel-${tab.id}`} aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "active" : ""} id={`system-tab-${tab.id}`} key={tab.id} onClick={() => activateTab(tab.id)} onKeyDown={(event) => handleTabKey(event, index)} ref={(node) => { tabRefs.current[index] = node; }} role="tab" tabIndex={activeTab === tab.id ? 0 : -1} type="button"><Icon size={17} />{tab.label}</button>; })}
        </div>

        <div aria-labelledby={`system-tab-${activeTab}`} className="system-tab-panel" id={`system-panel-${activeTab}`} role="tabpanel">
          {activeTab === "users" ? <>
            <SectionHeader action={<button className="action-button secondary" disabled={!canEditUsers} onClick={runIdentitySync} type="button"><RefreshCw size={16} />{t("systemSyncNow")}</button>} description={t("systemUserManagementDescription")} title={t("systemUserManagementTitle")} />
            <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchUsers")} onChange={(event) => setUserQuery(event.target.value)} placeholder={t("systemSearchUsersPlaceholder")} value={userQuery} /></label><select aria-label={t("systemFilterIdentitySource")} onChange={(event) => setUserSourceFilter(event.target.value)} value={userSourceFilter}><option value="all">{t("systemAllIdentitySources")}</option>{Array.from(new Set(liveUsers.map((user) => user.source))).map((source) => <option key={source} value={source}>{source}</option>)}</select><span>{format("systemUserCount", { filtered: filteredUsers.length, total: liveUsers.length })}</span></div>
            {filteredUsers.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemUser")}</th><th>{t("systemDepartment")}</th><th>{t("systemIdentitySourceColumn")}</th><th>{t("systemRoleColumn")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{filteredUsers.map((user) => <tr key={user.id}><td><strong>{userRowName(user)}</strong><small>{user.email}</small></td><td>{user.department}</td><td>{user.source}</td><td>{user.roles}</td><td><StateBadge tone={user.status === "active" ? "green" : "gray"}>{localizedStatus(user.status)}</StateBadge></td><td><div className="system-row-actions"><button aria-label={format("systemViewUser", { name: userRowName(user) })} className="icon-text-button" onClick={() => setModal({ type: "user", user })} type="button">{t("systemView")} <ChevronRight size={15} /></button><button className="icon-text-button" disabled={!canEditUsers} onClick={() => setModal({ type: "confirm", title: `${user.status === "active" ? t("systemDisable") : t("systemEnable")}${t("systemUser")}`, message: format("systemConfirmToggleUser", { action: user.status === "active" ? t("systemDisable") : t("systemEnable"), name: userRowName(user) }), actionLabel: user.status === "active" ? t("systemDisable") : t("systemEnable"), run: () => toggleUser(user) })} type="button">{user.status === "active" ? t("systemDisable") : t("systemEnable")}</button></div></td></tr>)}</tbody></table></div> : <EmptyInlineState />}
          </> : null}

          {activeTab === "roles" ? <>
            <SectionHeader action={rolesView === "local" ? <button className="action-button" disabled={!canCreateRoles} onClick={() => setModal({ type: "role" })} type="button"><UserRoundCog size={16} />{t("systemAddRole")}</button> : undefined} description={t("systemRolesDescription")} title={t("systemRolesTitle")} />
            <div aria-label={t("systemRoleTypeViews")} className="system-role-type-tabs" role="tablist">
              <button aria-selected={rolesView === "local"} className={rolesView === "local" ? "active" : ""} onClick={() => setRolesView("local")} role="tab" type="button"><ShieldCheck size={16} />{t("systemLocalRoles")}<span>{liveRoles.length}</span></button>
              <button aria-selected={rolesView === "ldap"} className={rolesView === "ldap" ? "active" : ""} onClick={() => setRolesView("ldap")} role="tab" type="button"><DatabaseZap size={16} />{t("systemLdapGroups")}<span>{ldapGroups.length}</span></button>
            </div>
            {rolesView === "local" ? <>
              <div className="system-role-toolbar">
                <label><Search size={16} /><input aria-label={t("systemSearchRoles")} onChange={(event) => setRoleQuery(event.target.value)} placeholder={t("systemSearchRolesPlaceholder")} value={roleQuery} /></label>
                <div aria-label={t("systemRoleStatusFilter")} className="system-role-status-filter" role="group">
                  {(["all", "enabled", "disabled"] as RoleStatusFilter[]).map((status) => <button aria-pressed={roleStatusFilter === status} className={roleStatusFilter === status ? "active" : ""} key={status} onClick={() => setRoleStatusFilter(status)} type="button">{status === "all" ? t("systemRoleFilterAll") : status === "enabled" ? t("systemEnabled") : t("systemDisabled")}</button>)}
                </div>
                <span aria-live="polite">{format("systemRoleResultCount", { filtered: filteredLocalRoles.length, total: liveRoles.length })}</span>
              </div>
              {filteredLocalRoles.length ? <div className="system-role-grid">{filteredLocalRoles.map(renderLocalRoleCard)}</div> : <EmptyInlineState>{liveRoles.length ? t("systemNoMatchingRoles") : t("systemNoLocalRoles")}</EmptyInlineState>}
            </> : null}
            {rolesView === "ldap" ? <div className="system-ldap-groups"><div className="system-subsection-title"><div><h3><DatabaseZap size={18} />{t("systemLdapGroups")}</h3><p>{t("systemExternalGroupMappingsDescription")}</p></div></div>{ldapGroups.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemLdapGroup")}</th><th>{t("systemLdapPath")}</th><th>{t("systemMembersColumn")}</th><th>{t("systemNomoSmartRole")}</th><th>{t("systemStatusColumn")}</th></tr></thead><tbody>{ldapGroups.map((group) => { const mapping = liveGroupMappings.find((item) => item.groupId === group.id); return <tr key={group.id}><td><strong>{group.group_name}</strong><small>{t("systemLdapReadOnly")}</small></td><td>{group.path}</td><td>{group.member_count}</td><td>{mapping?.role ?? t("systemNoMapping")}</td><td><StateBadge tone={group.is_active ? "green" : "gray"}>{group.is_active ? t("systemSynced") : t("systemDisabled")}</StateBadge></td></tr>; })}</tbody></table></div> : <EmptyInlineState />}</div> : null}
          </> : null}

          {activeTab === "permissions" ? <>
            <SectionHeader action={<div className="system-save-state"><span>{permissionSaved ? <><Check size={15} />{t("systemSaved")}</> : t("systemUnsavedChanges")}</span><button className="action-button" disabled={!canEditPermissions || selectedRoleReadOnly} onClick={savePermissions} title={!canEditPermissions ? t("apiForbidden") : selectedRoleReadOnly ? t("systemRoleReadOnly") : undefined} type="button"><Save size={16} />{t("systemSavePermissions")}</button></div>} description={t("systemPermissionsDescription")} title={t("systemPermissions")} />
            <div className="role-selector" aria-label={t("systemSelectRole")}>{liveRoles.map((role) => <button aria-pressed={selectedRole === role.id} className={`${selectedRole === role.id ? "active" : ""}${role.isActive === false ? " inactive" : ""}`} key={role.id} onClick={() => { setSelectedRole(role.id); setPermissionSaved(true); }} type="button"><span>{role.name}</span><small>{format("systemRoleSelectorSummary", { members: role.members, groups: role.groups })} · {role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</small></button>)}</div>
            {selectedRoleReadOnly ? <div className="system-role-readonly-banner"><LockKeyhole size={16} /><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRolePermissionsReadOnlyHelp")}</p></div></div> : null}
            {liveRoles.length ? <div className="permission-matrix-wrap"><table className="permission-matrix-table"><thead><tr><th>{t("systemMenuPermission")}</th><th>{t("permissionActionView")}</th><th>{t("permissionActionCreate")}</th><th>{t("permissionActionEdit")}</th><th>{t("permissionActionDelete")}</th><th>{t("permissionActionExecute")}</th></tr></thead><tbody>{permissionMenuRows.map((row) => { const state = permissions[selectedRole]?.[row.key] ?? emptyPermissionState()[row.key]; return <tr key={row.key}><td><strong>{t(row.labelKey as TranslationKey)}</strong><small>{t(row.descriptionKey as TranslationKey)}</small></td>{(["view", "create", "edit", "delete", "execute"] as PermissionAction[]).map((action) => { const enabled = permissionActionEnabled(row, action); return <td key={action}><input aria-label={`${liveRoles.find((role) => role.id === selectedRole)?.name ?? t("systemRoleColumn")} ${t(row.labelKey as TranslationKey)} ${t(`permissionAction${action.charAt(0).toUpperCase()}${action.slice(1)}` as TranslationKey)}`} checked={enabled && state[action]} disabled={!canEditPermissions || selectedRoleReadOnly || !enabled} onChange={() => togglePermission(row.key, action)} type="checkbox" /></td>; })}</tr>; })}</tbody></table></div> : <EmptyInlineState />}
          </> : null}

          {activeTab === "models" ? <>
            <SectionHeader action={<button className="action-button" disabled={!canCreateModels} onClick={() => openModelModal()} type="button"><Bot size={16} />{t("systemAddModel")}</button>} description={t("systemModelsDescription")} title={t("systemModels")} />
            <div className="model-list-toolbar">
              <label><span>{t("systemModelTypeFilter")}</span><select aria-label={t("systemModelTypeFilter")} onChange={(event) => { setModelTableType(event.target.value); setModelTablePage(1); }} value={modelTableType}><option value="all">{t("systemAllModelTypes")}</option><option value="Chat">{t("labelChat")}</option><option value="Embedding">Embedding</option><option value="OCR">OCR</option><option value="Judge">Judge</option></select></label>
              <span aria-live="polite">{format("systemModelResultRange", { first: modelTableFirst, last: modelTableLast, total: modelTableTotal })}</span>
            </div>
            {modelTableError ? <div className="error-summary" role="alert"><strong>{localize(modelTableError)}</strong><button className="icon-text-button" onClick={() => { void refreshModelTable(); }} type="button"><RefreshCw size={14} />{t("retry")}</button></div> : null}
            {modelTableLoading ? <div className="system-table-loading" role="status"><LoaderCircle className="spin" size={20} /><span>{t("systemLoadingModels")}</span></div> : null}
            {!modelTableLoading && modelTableRows.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemName")}</th><th>{t("systemModelType")}</th><th>{t("labelProvider")}</th><th>{t("systemModel")}</th><th>{t("systemSecret")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{modelTableRows.map((model) => {
              const modelIsActive = model.status === "active";
              return <tr key={model.id}><td><strong>{model.name}</strong>{model.default ? <small>{format("systemDefaultModelLabel", { type: model.type })}</small> : null}</td><td>{model.type}</td><td>{model.provider}</td><td>{aiModelProviderName(model.raw?.config)}</td><td><span className="secret-state"><LockKeyhole size={14} />{model.raw?.api_key_configured || model.raw?.api_key_secret_ref ? t("systemConfigured") : t("systemNotConfigured")}</span></td><td><div className="model-status-stack"><StateBadge tone={modelIsActive ? "green" : "gold"}>{localizedStatus(model.status)}</StateBadge>{model.raw?.last_test_status ? <><StateBadge tone={model.raw.last_test_status === "success" ? "green" : model.raw.last_test_status === "failed" ? "coral" : "gold"}>{localizedOperationStatus(model.raw.last_test_status)}</StateBadge><small>{model.raw.last_tested_at ? new Date(model.raw.last_tested_at).toLocaleString() : null}{model.raw.last_test_latency_ms !== null ? ` · ${model.raw.last_test_latency_ms} ms` : ""}</small></> : <small>{t("systemConnectionNotTested")}</small>}</div></td><td><div className="system-row-actions"><button className="icon-text-button" disabled={!canEditModels} onClick={() => openModelModal(model)} type="button">{t("systemEdit")}</button><button className="icon-text-button" disabled={!canEditModels || model.default || !modelIsActive} onClick={async () => { await setDefaultModel(apiFetch, model.id); await refreshModels(); }} type="button">{t("systemSetDefault")}</button><button className="icon-text-button" disabled={!canEditModels} onClick={() => { void runModelConnectionTest(model); }} type="button">{t("systemTest")}</button>{modelIsActive ? <button className="icon-text-button" disabled={!canEditModels} onClick={() => setModal({ type: "confirm", title: t("systemDisableModel"), message: t("systemDisableModelHelp"), actionLabel: t("systemDisable"), run: () => deactivateModelRow(model) })} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={!canEditModels} onClick={() => { void activateModel(model); }} type="button">{t("systemEnable")}</button>}<button aria-label={format("systemDeleteModelAria", { name: model.name })} className="icon-text-button destructive" disabled={!canDeleteModels} onClick={() => openModelDeleteModal(model)} type="button"><Trash2 size={14} />{t("systemDelete")}</button></div></td></tr>;
            })}</tbody></table></div> : null}
            {!modelTableLoading && !modelTableRows.length && !modelTableError ? <EmptyInlineState>{t("systemNoModelsMatchFilter")}</EmptyInlineState> : null}
            <div className="model-list-pagination">
              <label><span>{t("systemRowsPerPage")}</span><select aria-label={t("systemRowsPerPage")} onChange={(event) => { setModelTablePageSize(Number(event.target.value)); setModelTablePage(1); }} value={modelTablePageSize}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label>
              <span>{format("systemPageOf", { page: modelTablePage, total: modelTableTotalPages })}</span>
              <div><button aria-label={t("systemPreviousPage")} className="icon-button" disabled={modelTableLoading || modelTablePage <= 1} onClick={() => setModelTablePage((page) => Math.max(1, page - 1))} type="button"><ChevronLeft size={17} /></button><button aria-label={t("systemNextPage")} className="icon-button" disabled={modelTableLoading || modelTablePage >= modelTableTotalPages} onClick={() => setModelTablePage((page) => Math.min(modelTableTotalPages, page + 1))} type="button"><ChevronRight size={17} /></button></div>
            </div>
          </> : null}

          {activeTab === "prompts" ? <>
            <SectionHeader description={t("systemPromptsDescription")} title={t("systemPrompts")} />
            {promptError ? <div className="error-summary" role="alert"><strong>{localize(promptError)}</strong></div> : null}
            {promptMessage ? <div className="fixture-banner"><Check size={17} /><div><strong>{t("systemSaved")}</strong><span>{localize(promptMessage)}</span></div></div> : null}
            <div className="system-prompt-layer-stack"><Layers3 size={17} /><div><strong>{t("systemPromptLayerOrderTitle")}</strong><span>{t("systemPromptLayerOrderHelp")}</span></div></div>
            <section className="system-prompt-area">
              <div className="system-subsection-title"><div><h3><Globe2 size={18} />{t("systemPromptGlobalSection")}</h3><p>{t("systemPromptGlobalSectionHelp")}</p></div></div>
              <div className="system-prompt-global-grid">
                {globalChatPrompt ? <button className={selectedPromptId === globalChatPrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalChatPrompt)} type="button"><span><MessageSquareText size={18} />{t("systemPromptGlobalChatTitle")}</span><strong>{format("systemVersionValue", { version: globalChatPrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalChatPrompt.is_active ? "green" : "gray"}>{globalChatPrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving} onClick={() => { void createGlobalPrompt("Chat"); }} type="button"><strong>{t("systemPromptGlobalChatTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
                {globalJudgePrompt ? <button className={selectedPromptId === globalJudgePrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalJudgePrompt)} type="button"><span><ShieldCheck size={18} />{t("systemPromptGlobalJudgeTitle")}</span><strong>{format("systemVersionValue", { version: globalJudgePrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalJudgePrompt.is_active ? "green" : "gray"}>{globalJudgePrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving} onClick={() => { void createGlobalPrompt("Judge"); }} type="button"><strong>{t("systemPromptGlobalJudgeTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
              </div>
            </section>
            <section className="system-prompt-area">
              <div className="system-subsection-title"><div><h3><Bot size={18} />{t("systemPromptModelSection")}</h3><p>{t("systemPromptModelSectionHelp")}</p></div><div className="system-toolbar compact"><select aria-label={t("systemPromptSelectModel")} onChange={(event) => setPromptModelDraft(event.target.value)} value={promptModelDraft}>{promptModelOptions.length ? promptModelOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.type}</option>) : <option value="">{t("systemPromptNoModelsAvailable")}</option>}</select><button className="action-button secondary" disabled={!canCreateModels || !promptModelDraft || promptSaving} onClick={() => { void createModelPrompt(); }} type="button"><Plus size={16} />{t("systemPromptAddModel")}</button></div></div>
              {modelSpecificPrompts.length ? <div className="system-table-wrap system-prompt-model-table"><table className="system-table"><thead><tr><th>{t("systemModel")}</th><th>{t("systemModelType")}</th><th>{t("systemVersion")}</th><th>{t("systemStatusColumn")}</th></tr></thead><tbody>{modelSpecificPrompts.map((prompt) => <tr className={selectedPromptId === prompt.id ? "selected-row" : ""} key={prompt.id} onClick={() => selectPrompt(prompt)}><td><strong>{liveModels.find((model) => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—"}</strong><small>{prompt.content_hash ?? t("systemPromptBlankHash")}</small></td><td>{prompt.model_type}</td><td>{prompt.current_version_number ?? "—"}</td><td><StateBadge tone={prompt.is_active ? "green" : "gray"}>{prompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></td></tr>)}</tbody></table></div> : <EmptyInlineState>{t("systemPromptNoModelPrompts")}</EmptyInlineState>}
            </section>
          </> : null}

          {activeTab === "apiKeys" ? <>
            <SectionHeader
              action={<div className="system-section-actions"><button className="action-button secondary" onClick={() => { void refreshIntegrationClients(); }} type="button"><RefreshCw size={16} />{t("refresh")}</button><button className="action-button" disabled={!canCreateSystemManagement} onClick={openApiKeyCreateModal} type="button"><Plus size={16} />{t("systemApiKeyCreateTitle")}</button></div>}
              description={t("systemApiKeysDescription")}
              title={t("systemApiKeys")}
            />
            <section className="system-api-key-list">
              <div className="system-subsection-title"><div><h3>{t("systemApiKeyListTitle")}</h3><p>{t("systemApiKeyListHelp")}</p></div></div>
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
              })}</div> : <EmptyInlineState>{t("systemApiKeyEmpty")}</EmptyInlineState>}
            </section>
          </> : null}

          {activeTab === "identity" ? <>
            <SectionHeader
              action={canEditSystemManagement ? (identityUnlocked ? <div className="system-save-state"><span className="identity-unlock-countdown"><Clock3 size={15} />{t("identityUnlockRemaining")} {remainingIdentityTime}</span><button className="action-button secondary" onClick={lockIdentitySettings} type="button"><LockKeyhole size={16} />{t("identityCancelAndLock")}</button><button className="action-button" onClick={saveIdentitySettings} type="button"><Save size={16} />{t("identityValidateAndSave")}</button></div> : <button className="action-button" onClick={openIdentityReauthDialog} ref={identityReauthTriggerRef} type="button"><ShieldCheck size={16} />{t("identityReauthToEdit")}</button>) : null}
              description={t("identitySettingsDescription")}
              title={t("identitySettingsTitle")}
            />
            <div aria-live="polite" className={`identity-lock-banner ${identityUnlocked ? "unlocked" : ""}`}><span>{identityUnlocked ? <KeyRound size={18} /> : <LockKeyhole size={18} />}</span><div><strong>{identityUnlocked ? t("identityTemporarilyUnlocked") : t("identitySettingsLocked")}</strong><p>{identityUnlocked ? t("identityUnlockedHelp") : t("identityLockedHelp")}</p></div><StateBadge tone={identityUnlocked ? "gold" : "green"}>{identityUnlocked ? t("identityEditing") : t("identityReadOnly")}</StateBadge></div>
            {visibleIdentityMessage ? <p className="identity-message" role="status">{localize(visibleIdentityMessage)}</p> : null}

            <fieldset className="identity-settings-section" disabled={!identityUnlocked || !canEditSystemManagement}>
              <legend><span><KeyRound size={19} /></span><div><small>{t("identityPrimaryProvider")}</small><strong>Keycloak OIDC</strong></div><StateBadge tone={statusTone(identityProviderStatus)}>{identityProviderComponent ? localizedOperationStatus(identityProviderStatus) : t("identityUnknown")}</StateBadge></legend>
              <div className="identity-form-grid identity-oidc-form-grid">
                <label className={`identity-field ${identityErrors.issuer ? "has-error" : ""}`} htmlFor="identity-issuer">
                  <span>{t("labelIssuer")}</span>
                  <input aria-describedby={identityErrors.issuer ? "identity-issuer-error" : undefined} aria-invalid={Boolean(identityErrors.issuer)} id="identity-issuer" onChange={(event) => updateIdentity("issuer", event.target.value)} value={identitySettings.issuer} />
                  {identityErrors.issuer ? <small className="identity-field-error" id="identity-issuer-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("issuer")}</small> : null}
                </label>
                <label className={`identity-field ${identityErrors.realm ? "has-error" : ""}`} htmlFor="identity-realm">
                  <span>{t("labelRealm")}</span>
                  <input aria-describedby={identityErrors.realm ? "identity-realm-error" : undefined} aria-invalid={Boolean(identityErrors.realm)} id="identity-realm" onChange={(event) => updateIdentity("realm", event.target.value)} value={identitySettings.realm} />
                  {identityErrors.realm ? <small className="identity-field-error" id="identity-realm-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("realm")}</small> : null}
                </label>
                <label className={`identity-field ${identityErrors.clientId ? "has-error" : ""}`} htmlFor="identity-client-id">
                  <span>{t("labelClientId")}</span>
                  <input aria-describedby={identityErrors.clientId ? "identity-client-id-error" : undefined} aria-invalid={Boolean(identityErrors.clientId)} id="identity-client-id" onChange={(event) => updateIdentity("clientId", event.target.value)} value={identitySettings.clientId} />
                  {identityErrors.clientId ? <small className="identity-field-error" id="identity-client-id-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("clientId")}</small> : null}
                </label>
                <label className={`identity-field ${identityErrors.audience ? "has-error" : ""}`} htmlFor="identity-audience">
                  <span>{t("labelAudience")}</span>
                  <input aria-describedby={identityErrors.audience ? "identity-audience-error" : undefined} aria-invalid={Boolean(identityErrors.audience)} id="identity-audience" onChange={(event) => updateIdentity("audience", event.target.value)} value={identitySettings.audience} />
                  {identityErrors.audience ? <small className="identity-field-error" id="identity-audience-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("audience")}</small> : null}
                </label>
                <label className={`identity-field identity-wide-field ${identityErrors.discoveryUrl ? "has-error" : ""}`} htmlFor="identity-discovery-url">
                  <span>{t("labelDiscoveryJwksUrl")}</span>
                  <input aria-describedby={identityErrors.discoveryUrl ? "identity-discovery-url-error" : undefined} aria-invalid={Boolean(identityErrors.discoveryUrl)} id="identity-discovery-url" onChange={(event) => updateIdentity("discoveryUrl", event.target.value)} value={identitySettings.discoveryUrl} />
                  {identityErrors.discoveryUrl ? <small className="identity-field-error" id="identity-discovery-url-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("discoveryUrl")}</small> : null}
                </label>
                <div className="identity-oidc-meta identity-wide-field">
                  <label className="identity-toggle"><input checked={identitySettings.keycloakEnabled} onChange={(event) => updateIdentity("keycloakEnabled", event.target.checked)} type="checkbox" /><span>{t("identityUseKeycloak")}</span></label>
                  <div className="identity-secret-status"><span>{t("labelClientSecret")}</span><strong><LockKeyhole size={14} />{identitySecretConfigured ? t("identitySecretConfigured") : t("identitySecretNotConfigured")}</strong></div>
                  <div className="identity-secret-status"><span>{t("identityConfigurationSource")}</span><strong>{identityConfigurationSource === "database" ? t("identitySourceDatabase") : t("identitySourceDeployment")}</strong></div>
                </div>
              </div>
            </fieldset>

            <fieldset className="identity-settings-section">
              <legend><span><DatabaseZap size={19} /></span><div><small>{t("identityDirectorySync")}</small><strong>{t("identitySharedDirectoryPolicy")}</strong></div><StateBadge tone={directoryProviderError ? "coral" : directoryProviders.length ? "green" : "gray"}>{directoryProviderError ? t("systemOpUnavailable") : directoryProviders.length ? t("identityConfigured") : t("systemNotConfigured")}</StateBadge></legend>
              <div className="identity-directory-policy">
                <label className="identity-toggle"><input checked={identitySettings.syncEnabled} disabled={!identityUnlocked || !canEditSystemManagement} onChange={(event) => updateIdentity("syncEnabled", event.target.checked)} type="checkbox" /><span>{t("identitySyncEnabled")}</span></label>
                <label><span>{t("identitySyncScope")}</span><select disabled={!identityUnlocked || !canEditSystemManagement} onChange={(event) => updateIdentity("syncScope", event.target.value as IdentitySettings["syncScope"])} value={identitySettings.syncScope}><option value="people_and_groups">{t("identityPeopleAndGroups")}</option><option value="people">{t("identityPeopleOnly")}</option><option value="groups">{t("identityGroupsOnly")}</option></select></label>
              </div>
              <div className="identity-schedule-row">
                <label className={`identity-field ${identityErrors.schedule ? "has-error" : ""}`} htmlFor="identity-sync-schedule">
                  <span>{t("identitySyncSchedule")}</span>
                  <input aria-describedby={identityErrors.schedule ? "identity-sync-schedule-error" : undefined} aria-invalid={Boolean(identityErrors.schedule)} disabled={!identityUnlocked || !canEditSystemManagement} id="identity-sync-schedule" onChange={(event) => updateIdentity("schedule", event.target.value)} value={identitySettings.schedule} />
                  {identityErrors.schedule ? <small className="identity-field-error" id="identity-sync-schedule-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("schedule")}</small> : null}
                </label>
                <label className={`identity-field ${identityErrors.timezone ? "has-error" : ""}`} htmlFor="identity-timezone">
                  <span>{t("systemIdentityTimezone")}</span>
                  <input aria-describedby={identityErrors.timezone ? "identity-timezone-error" : undefined} aria-invalid={Boolean(identityErrors.timezone)} disabled={!identityUnlocked || !canEditSystemManagement} id="identity-timezone" onChange={(event) => updateIdentity("timezone", event.target.value)} value={identitySettings.timezone} />
                  {identityErrors.timezone ? <small className="identity-field-error" id="identity-timezone-error" role="alert"><AlertTriangle aria-hidden="true" size={13} />{identityErrorMessage("timezone")}</small> : null}
                </label>
                <button className="action-button secondary identity-sync-action" disabled={!canEditSystemManagement || identitySyncing || Boolean(activeIdentityRun) || !identityWorkerAvailable} onClick={runIdentitySync} type="button">{identitySyncing || activeIdentityRun ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{identitySyncing || activeIdentityRun ? t("identitySyncInProgress") : t("identitySyncNow")}</button>
              </div>
              <div className="identity-directory-heading"><div><strong>{t("identityDirectoryProviders")}</strong><small>{t("identityDirectoryProvidersHelp")}</small></div></div>
              {directoryProviderError ? <div className="identity-provider-error"><AlertTriangle size={17} />{t("identityDirectoryProviderUnavailable")}</div> : null}
              <div className="directory-settings-grid">
                {directoryProviders.map((provider) => <article className="directory-setting-card" key={provider.id}><header><div><h3>{provider.name}</h3><p>{provider.vendor} · {provider.id}</p></div><StateBadge tone={provider.enabled ? "green" : "gray"}>{provider.enabled ? t("systemEnabled") : t("systemDisabled")}</StateBadge></header><label><span>{t("identityDirectoryFilter")}</span><textarea disabled={!identityUnlocked || !canEditSystemManagement} onChange={(event) => setDirectoryFilterDrafts((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder={t("identityDirectoryFilterPlaceholder")} rows={3} value={directoryFilterDrafts[provider.id] ?? ""} /><small>{t("identityDirectoryFilterHelp")}</small></label><footer><small>{format("identityProviderCheckedAt", { time: provider.checked_at.slice(0, 16).replace("T", " ") })}</small><button className="action-button secondary" disabled={!identityUnlocked || !canEditSystemManagement || savingDirectoryProviderId !== null} onClick={() => { void saveDirectoryFilter(provider); }} type="button">{savingDirectoryProviderId === provider.id ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}{t("identitySaveFilter")}</button></footer></article>)}
              </div>
              {!directoryProviderError && !directoryProviders.length ? <EmptyInlineState>{t("identityDirectoryProviderEmpty")}</EmptyInlineState> : null}
            </fieldset>

            <div className="identity-grid">
              <article className="identity-sync-card"><header><div><small>{t("identityDirectorySync")}</small><h3>{t("identityLastSync")}</h3></div><StateBadge tone={syncRuns[0]?.status === "failed" ? "coral" : syncRuns[0]?.status === "running" || syncRuns[0]?.status === "queued" ? "gold" : "green"}>{syncRuns[0] ? identitySyncStatusText(syncRuns[0].status, t) : t("identitySuccess")}</StateBadge></header><strong>{syncRuns[0]?.started_at?.slice(0, 16).replace("T", " ") ?? t("identityNoSyncRecord")}</strong><p>{syncRuns[0] ? `${identitySyncScopeText(syncRuns[0].requested_scope, t)} · ${format("identityUsersCount", { count: syncRuns[0].users_created + syncRuns[0].users_updated })} · ${format("identityGroupsCount", { count: syncRuns[0].groups_created + syncRuns[0].groups_updated })}` : t("identityWaitingFirstSync")}</p>{syncRuns[0]?.provider_results.length ? <ul className="identity-provider-results" aria-label={t("identitySyncProviderResults")}>
                {syncRuns[0].provider_results.map((provider) => <li key={provider.id}><span><strong>{provider.provider_name}</strong><small>{provider.provider_vendor}</small></span><span>{t("identitySyncProviderUsers")}: {identitySyncStatusText(provider.user_sync_status, t)}</span><span>{t("identitySyncProviderGroups")}: {identitySyncStatusText(provider.group_sync_status, t)}</span><StateBadge tone={provider.status === "failed" ? "coral" : provider.status === "running" || provider.status === "pending" ? "gold" : provider.status === "skipped" ? "gray" : "green"}>{identitySyncStatusText(provider.status, t)}</StateBadge></li>)}
              </ul> : syncRuns[0] && !["queued", "provider_discovery"].includes(syncRuns[0].phase) ? <p className="identity-provider-empty-result"><Info size={14} />{t("identitySyncNoProviderResults")}</p> : null}<div><span>{format("identityCreatedCount", { count: syncRuns[0]?.users_created ?? 0 })}</span><span>{format("identityUpdatedCount", { count: syncRuns[0]?.users_updated ?? 0 })}</span><span>{format("identityDisabledCount", { count: syncRuns[0]?.users_disabled ?? 0 })}</span></div><div className="system-sync-history">{syncRuns.slice(0, 5).map((run) => <span key={run.id}>{identitySyncStatusText(run.status, t)} · {identitySyncScopeText(run.requested_scope, t)} · {run.started_at?.slice(0, 10) ?? t("identityQueuedShort")}</span>)}</div></article>
              <article className="identity-break-glass-card">
                <header>
                  <span>{breakGlassStatus?.status === "configured_disabled" ? <FileCheck2 size={18} /> : <AlertTriangle size={18} />}</span>
                  <div><small>{t("identityEmergencyAccess")}</small><h3>{breakGlassStatus?.username ?? t("identityBreakGlassFallback")}</h3></div>
                  <StateBadge tone={breakGlassTone(breakGlassStatus?.status)}>{localizedBreakGlassStatus(breakGlassStatus?.status)}</StateBadge>
                </header>
                <p>{t("identityBreakGlassHelp")}</p>
                <dl>
                  <div><dt>{t("identitySource")}</dt><dd>{evidenceText(breakGlassStatus?.local_account, t)}</dd></div>
                  <div><dt>{t("identityBreakGlassNormalState")}</dt><dd>{breakGlassNormalStateText(breakGlassStatus, t)}</dd></div>
                  <div><dt>{t("identityBreakGlassSystemAdmin")}</dt><dd>{evidenceText(breakGlassStatus?.system_admin_mapped, t)}</dd></div>
                  <div><dt>{t("identityCredentialUpdate")}</dt><dd>{evidenceText(breakGlassStatus?.credential_update_required, t)}</dd></div>
                  <div><dt>{t("identityCredential")}</dt><dd>{t("identityDeploymentSecret")}</dd></div>
                  <div><dt>{t("identityLifecycleControl")}</dt><dd>{evidenceStateText(breakGlassStatus?.lifecycle_control, t)}</dd></div>
                  <div><dt>{t("identityRunbookEvidence")}</dt><dd>{evidenceStateText(breakGlassStatus?.runbook_evidence, t)}</dd></div>
                  <div><dt>{t("identityAlertingEvidence")}</dt><dd>{evidenceStateText(breakGlassStatus?.alerting_evidence, t)}</dd></div>
                </dl>
                <small className="identity-break-glass-check">{breakGlassStatus ? format("identityBreakGlassCheckedAt", { time: breakGlassStatus.checked_at.slice(0, 16).replace("T", " ") }) : t("identityNotVerified")}</small>
              </article>
            </div>
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("identityFederationBoundary")}</strong><p>{t("identityFederationBoundaryHelp")}</p></div></div>

            {reauthOpen ? <div className="system-modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape" && !identityReauthBusy) dismissIdentityReauth(); }} onMouseDown={(event) => { if (event.target === event.currentTarget && !identityReauthBusy) dismissIdentityReauth(); }} role="presentation">
              <section aria-describedby="reauth-description" aria-labelledby="reauth-title" aria-modal="true" className="system-reauth-modal" role="dialog">
                <header><span><ShieldCheck size={20} /></span><div><small>{t("identityProtectedAction")}</small><h2 id="reauth-title">{t("identityConfirmIdentity")}</h2></div><button aria-label={t("identityCloseDialog")} className="modal-close-button" disabled={identityReauthBusy} onClick={dismissIdentityReauth} type="button"><X size={18} /></button></header>
                <p id="reauth-description">{t("identityReauthExplanation")}</p>
                {identityReauthBusy ? <div aria-live="polite" className="identity-reauth-progress" role="status"><LoaderCircle aria-hidden="true" size={19} /><span>{t(identityReauthStatus === "opening" ? "identityReauthOpening" : "identityReauthCompleting")}</span></div> : null}
                {identityReauthError ? <div className="identity-reauth-error" role="alert"><AlertTriangle aria-hidden="true" size={18} /><span>{localize(identityReauthError)}</span></div> : null}
                <footer><button className="action-button secondary" disabled={identityReauthBusy} onClick={dismissIdentityReauth} type="button">{t("identityCancel")}</button><button autoFocus className="action-button" disabled={identityReauthBusy} onClick={beginIdentityReauthentication} type="button">{identityReauthStatus === "error" ? <RefreshCw size={16} /> : <LogIn size={16} />}{t(identityReauthStatus === "error" ? "identityReauthRetry" : "identityContinueKeycloak")}</button></footer>
              </section>
            </div> : null}
          </> : null}

          {activeTab === "status" ? <>
            <SectionHeader action={<button className="action-button secondary" onClick={() => { void refreshSystemStatus(); }} type="button"><RefreshCw size={16} />{t("refresh")}</button>} description={t("systemStatusDescription")} title={t("systemStatus")} />
            <div className="fixture-banner"><Activity size={17} /><div><strong>{t("liveData")}</strong><span>{t("systemStatusLiveHelp")}</span></div></div>
            {systemStatus ? <>
              <div className="system-status-grid">
              {[
                systemStatus.worker,
                systemStatus.queue,
                systemStatus.retrieval
              ].map((component) => <article className="system-status-card" key={component.name}><header><div><small>{component.name}</small><h3>{component.detail_code}</h3></div><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></header><dl>{metricPairs(component.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl><small>{format("systemCheckedAt", { time: component.checked_at.slice(0, 16).replace("T", " ") })}</small></article>)}
              </div>
              <div className="system-status-columns">
              <section>
                <h3>{t("systemDependencies")}</h3>
                <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemComponent")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemChecked")}</th></tr></thead><tbody>{systemStatus.dependencies.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></td><td>{component.detail_code}</td><td>{component.checked_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div>
              </section>
              <section>
                <h3>{t("systemAiProviders")}</h3>
                <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemProviderRole")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemMetrics")}</th></tr></thead><tbody>{systemStatus.providers.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></td><td>{component.detail_code}</td><td>{metricPairs(component.metrics).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—"}</td></tr>)}</tbody></table></div>
              </section>
              </div>
              <section className="system-status-errors">
              <h3>{t("systemRecentErrors")}</h3>
              {systemStatus.recent_errors.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemSourceColumn")}</th><th>{t("systemAction")}</th><th>{t("systemResult")}</th><th>{t("systemCode")}</th><th>{t("systemTime")}</th></tr></thead><tbody>{systemStatus.recent_errors.map((error) => <tr key={`${error.source}-${error.action}-${error.created_at}`}><td>{error.source}</td><td>{error.action}</td><td><StateBadge tone={statusTone(error.result === "success" ? "healthy" : "degraded")}>{localizedOperationStatus(error.result)}</StateBadge></td><td>{error.detail_code}</td><td>{error.created_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div> : <div className="empty-inline-state"><Check size={18} />{t("systemNoRecentErrors")}</div>}
              </section>
            </> : <EmptyInlineState>{t("systemStatusUnavailable")}</EmptyInlineState>}
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemSecurityMasking")}</strong><p>{t("systemSecurityMaskingHelp")}</p></div></div>
          </> : null}

          {activeTab === "parameters" ? <>
            <SectionHeader action={<div className="system-save-state"><button className="action-button secondary" disabled={!canEditParameters} onClick={restoreParameters} type="button"><RotateCcw size={16} />{t("systemRestoreDefaults")}</button><button className="action-button" disabled={!canEditParameters} onClick={saveParameters} title={!canEditParameters ? t("apiForbidden") : undefined} type="button"><Save size={16} />{t("systemSaveParameters")}</button></div>} description={t("systemParametersDescription")} title={t("systemParameters")} />
            <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("liveData")}</strong><span>{t("systemParametersLiveHelp")}</span></div></div>
            <div className="parameter-grid" data-session-draft-key="system.parameters">
              <label className={parameterErrors.uploadLimitMb ? "has-error" : ""}><span>{t("systemUploadLimitLabel")} <em>MB</em></span><input aria-describedby="upload-limit-help" data-session-draft-field="uploadLimitMb" max={1024} min={1} onChange={(event) => updateParameter("uploadLimitMb", Number(event.target.value))} type="number" value={parameters.uploadLimitMb} /><small id="upload-limit-help">{t("systemUploadLimitHelp")}</small>{parameterErrors.uploadLimitMb ? <strong>{parameterErrors.uploadLimitMb}</strong> : null}</label>
              <label className={parameterErrors.timezone ? "has-error" : ""}><span>{t("systemDefaultTimezoneLabel")} <em>{t("systemIdentityTimezone")}</em></span><input aria-describedby="timezone-help" data-session-draft-field="timezone" onChange={(event) => updateParameter("timezone", event.target.value)} value={parameters.timezone} /><small id="timezone-help">{t("systemDefaultTimezoneHelp")}</small>{parameterErrors.timezone ? <strong>{parameterErrors.timezone}</strong> : null}</label>
              <label className={parameterErrors.stagingTtlDays ? "has-error" : ""}><span>{t("systemStagingTtlLabel")} <em>{t("systemDaysUnit")}</em></span><input aria-describedby="ttl-help" data-session-draft-field="stagingTtlDays" max={90} min={1} onChange={(event) => updateParameter("stagingTtlDays", Number(event.target.value))} type="number" value={parameters.stagingTtlDays} /><small id="ttl-help">{t("systemStagingTtlHelp")}</small>{parameterErrors.stagingTtlDays ? <strong>{parameterErrors.stagingTtlDays}</strong> : null}</label>
              <label className={parameterErrors.sessionDraftTtlMinutes ? "has-error" : ""}><span>{t("systemSessionDraftTtlLabel")} <em>{t("systemMinutesUnit")}</em></span><input aria-describedby="draft-ttl-help" data-session-draft-field="sessionDraftTtlMinutes" max={120} min={0} onChange={(event) => updateParameter("sessionDraftTtlMinutes", Number(event.target.value))} type="number" value={parameters.sessionDraftTtlMinutes} /><small id="draft-ttl-help">{t("systemSessionDraftTtlHelp")}</small>{parameterErrors.sessionDraftTtlMinutes ? <strong>{parameterErrors.sessionDraftTtlMinutes}</strong> : null}</label>
            </div>
            <div aria-live="polite" className="parameter-footer"><div><Clock3 size={16} /><span>{t("systemParametersLiveValues")}</span></div>{parameterMessage ? <p>{localize(parameterMessage)}</p> : null}<small>{format("systemParametersSavedSummary", { uploadLimitMb: savedParameters.uploadLimitMb, timezone: savedParameters.timezone, stagingTtlDays: savedParameters.stagingTtlDays, sessionDraftTtlMinutes: savedParameters.sessionDraftTtlMinutes })}</small></div>
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemDeploymentSettingsExcluded")}</strong><p>{t("systemDeploymentSettingsExcludedHelp")}</p></div></div>
          </> : null}
        </div>
      </div>
      {activePromptEditor ? <div className="system-modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape" && !promptSaving) setPromptEditorOpen(false); }} onMouseDown={(event) => { if (event.target === event.currentTarget && !promptSaving) setPromptEditorOpen(false); }} role="presentation">
        <section aria-labelledby="system-prompt-editor-title" aria-modal="true" className="system-prompt-modal" role="dialog">
          <header><span><MessageSquareText size={20} /></span><div className="system-prompt-title-row"><h2 id="system-prompt-editor-title">{t("systemPromptEditor")}</h2><div className="system-prompt-badges"><StateBadge tone={activePromptEditor.prompt_scope === "global" ? "green" : "gold"}>{promptScopeLabel(activePromptEditor)}</StateBadge><StateBadge>{activePromptEditor.model_type}</StateBadge><StateBadge tone={activePromptEditor.is_active ? "green" : "gray"}>{activePromptEditor.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></div></div><button aria-label={t("systemPromptCloseEditor")} autoFocus className="modal-close-button" disabled={promptSaving} onClick={() => setPromptEditorOpen(false)} type="button"><X size={18} /></button></header>
          {renderPromptEditor(activePromptEditor)}
        </section>
      </div> : null}
      {apiKeyOneTime ? <div className="system-modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape") setApiKeyOneTime(null); }} onMouseDown={(event) => { if (event.target === event.currentTarget) setApiKeyOneTime(null); }} role="presentation">
        <section aria-labelledby="system-api-key-onetime-title" aria-modal="true" className="system-reauth-modal system-api-key-onetime-modal" role="dialog">
          <header><span><KeyRound size={20} /></span><div><small>{t("systemApiKeys")}</small><h2 id="system-api-key-onetime-title">{format("systemApiKeyOneTimeTitle", { name: apiKeyOneTime.name })}</h2></div><button aria-label={t("close")} className="modal-close-button" onClick={() => setApiKeyOneTime(null)} type="button"><X size={18} /></button></header>
          <div className="system-api-key-once" role="status"><KeyRound size={18} /><div><code>{apiKeyOneTime.key}</code><small>{t("systemApiKeyOneTimeHelp")}</small></div></div>
          <footer><button className="action-button secondary" onClick={() => { void navigator.clipboard.writeText(apiKeyOneTime.key); }} type="button">{t("systemApiKeyCopy")}</button><button className="action-button" onClick={() => setApiKeyOneTime(null)} type="button">{t("close")}</button></footer>
        </section>
      </div> : null}
      {modal ? <div className="system-modal-backdrop" onKeyDown={(event) => { if (event.key === "Escape" && !submitting) closeModal(); }} onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) closeModal(); }} role="presentation">
        <section aria-labelledby="system-crud-modal-title" aria-modal="true" className={`system-reauth-modal system-crud-modal${modal.type === "model-delete" ? " model-delete-modal" : modal.type === "role-delete" ? " role-delete-modal" : ""}`} role={modal.type === "role-delete" ? "alertdialog" : "dialog"}>
          <header><span>{modal.type === "api-key-create" || modal.type === "api-key-manage" ? <KeyRound size={20} /> : modal.type === "model-delete" || modal.type === "role-delete" ? <Trash2 size={20} /> : <Settings2 size={20} />}</span><div><small>{t("labelSystemManagement")}</small><h2 id="system-crud-modal-title">{modal.type === "user" ? t("systemUserDetails") : modal.type === "role" ? (modal.role ? (modal.role.isActive === false ? t("systemRoleDetails") : t("systemEditRole")) : t("systemAddRole")) : modal.type === "role-users" ? t("systemManualRoleUsers") : modal.type === "mapping" ? t("systemRoleMappingTitle") : modal.type === "role-delete" ? t("systemDeleteLocalRole") : modal.type === "model" ? (modal.model ? t("systemEditAiModel") : t("systemAddAiModel")) : modal.type === "model-delete" ? t("systemDeleteModelTitle") : modal.type === "api-key-create" ? t("systemApiKeyCreateTitle") : modal.type === "api-key-manage" ? t("systemApiKeyManageTitle") : localize(modal.title)}</h2></div><button aria-label={t("close")} className="modal-close-button" disabled={submitting} onClick={closeModal} type="button"><X size={18} /></button></header>
          {modalError ? <div className="error-summary" role="alert"><strong>{localize(modalError)}</strong></div> : null}
          {modal.type === "user" ? <form className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitUser(new FormData(event.currentTarget)); }}>
            <div className="system-detail-grid"><div><small>{t("systemName")}</small><strong>{userRowName(modal.user)}</strong></div><div><small>{t("labelEmail")}</small><strong>{modal.user.email}</strong></div><div><small>{t("systemSourceColumn")}</small><strong>{modal.user.source}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.user.status)}</strong></div></div>
            <label className="identity-toggle"><input defaultChecked={Boolean(modal.user.raw?.knowledge_owner)} name="knowledge_owner" type="checkbox" /><span>{t("labelKnowledgeOwner")}</span></label>
            <label><span>{t("systemManagerDelegateOptional")}</span><input name="manager_delegate_user_id" placeholder="UUID" /></label>
            <label><span>{t("labelSystemNotes")}</span><textarea defaultValue={modal.user.raw?.system_notes ?? ""} name="system_notes" rows={4} /></label>
            <footer><button className="action-button secondary" onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={!canEditUsers || submitting} type="submit"><Save size={16} />{t("save")}</button></footer>
          </form> : null}
          {modal.type === "role" ? <form className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitRole(new FormData(event.currentTarget)); }}>
            <label><span>{t("systemRoleName")}</span><input defaultValue={modal.role?.name ?? ""} disabled={modal.role?.isSystem || modal.role?.isActive === false} name="name" required /></label>
            <label><span>{t("systemDescription")}</span><textarea defaultValue={modal.role?.description ?? ""} disabled={modal.role?.isActive === false} name="description" rows={3} /></label>
            {modal.role?.isSystem ? <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemRoleProtection")}</strong><p>{t("systemRoleProtectionHelp")}</p></div></div> : null}
            {modal.role?.isActive === false ? <div className="system-role-readonly-banner"><LockKeyhole size={16} /><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleReadOnlyHelp")}</p></div></div> : null}
            <footer><button className="action-button secondary" onClick={() => setModal(null)} type="button">{modal.role?.isActive === false ? t("close") : t("cancel")}</button>{modal.role?.isActive === false ? null : <button className="action-button" disabled={submitting || (!modal.role && !canCreateRoles) || (Boolean(modal.role) && !canEditRoles)} type="submit"><Save size={16} />{t("save")}</button>}</footer>
          </form> : null}
          {modal.type === "role-users" ? <form className="system-crud-form role-user-editor" onSubmit={(event) => { event.preventDefault(); void saveRoleUsers(); }}>
            <p className="system-modal-help">{t("systemManualRoleUsersHelp")}</p>
            {modal.role.isActive === false ? <div className="system-role-readonly-banner"><LockKeyhole size={16} /><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleMembersReadOnlyHelp")}</p></div></div> : null}
            <div className="role-user-search-row">
              <label><Search size={16} /><input aria-label={t("systemRoleUserSearch")} autoFocus onChange={(event) => setRoleUserSearch(event.target.value)} placeholder={t("systemRoleUserSearchPlaceholder")} value={roleUserSearch} /></label>
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
            <footer><button className="action-button secondary" onClick={() => setModal(null)} type="button">{modal.role.isActive === false ? t("close") : t("cancel")}</button>{modal.role.isActive === false ? null : <button className="action-button" disabled={!canEditRoles || submitting} type="submit"><Save size={16} />{t("systemSaveUsers")}</button>}</footer>
          </form> : null}
          {modal.type === "mapping" ? <div className="system-crud-form">
            <p className="system-modal-help">{format("systemRoleMappingHelp", { role: modal.role.name })}</p>
            {modal.role.isActive === false ? <div className="system-role-readonly-banner"><LockKeyhole size={16} /><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleMappingReadOnlyHelp")}</p></div></div> : null}
            <div className="system-mapping-editor"><label><span>{t("systemLdapGroup")}<small>{t("systemOneToOneMappingHelp")}</small></span><select autoFocus disabled={modal.role.isActive === false || !canEditRoles} onChange={(event) => setMappingGroupDraft(event.target.value)} value={mappingGroupDraft}><option value="">{t("systemNoMapping")}</option>{availableMappingGroups.map((group) => <option key={group.id} value={group.id}>{group.path || group.group_name} · {format("systemMemberCount", { count: group.member_count })}</option>)}</select></label></div>
            <div className="system-security-note"><Info size={17} /><div><strong>{t("systemMappingImmediateTitle")}</strong><p>{t("systemMappingImmediateHelp")}</p></div></div>
            <footer><button className="action-button secondary" onClick={() => setModal(null)} type="button">{modal.role.isActive === false || !canEditRoles ? t("close") : t("cancel")}</button>{modal.role.isActive === false || !canEditRoles ? null : <button className="action-button" disabled={submitting} onClick={saveRoleMapping} type="button"><Save size={16} />{t("systemSaveMappings")}</button>}</footer>
          </div> : null}
          {modal.type === "role-delete" ? <div className="system-crud-form role-delete-content">
            <div className="role-delete-warning"><AlertTriangle size={20} /><div><strong>{t("systemDeleteRoleWarningTitle")}</strong><p>{t("systemDeleteRoleWarningHelp")}</p></div></div>
            <div className="system-detail-grid"><div><small>{t("systemRoleColumn")}</small><strong>{modal.role.name}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{modal.role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</strong></div><div><small>{t("systemMappedLdapGroup")}</small><strong>{externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.path || externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.group_name || t("systemNoMapping")}</strong></div><div><small>{t("systemMembersColumn")}</small><strong>{modal.role.members}</strong></div></div>
            <ul className="role-delete-impact"><li>{t("systemDeleteRoleImpactHidden")}</li><li>{t("systemDeleteRoleImpactMapping")}</li><li>{t("systemDeleteRoleImpactHistory")}</li></ul>
            <label><span>{format("systemDeleteRoleConfirmationLabel", { name: modal.role.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setRoleDeleteConfirmation(event.target.value)} placeholder={modal.role.name} value={roleDeleteConfirmation} /><small>{t("systemDeleteRoleConfirmationHelp")}</small></label>
            <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || roleDeleteConfirmation !== modal.role.name} onClick={() => { void submitRoleDelete(modal.role); }} type="button"><Trash2 size={16} />{t("systemDeleteRolePermanently")}</button></footer>
          </div> : null}
          {modal.type === "model" ? <form className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitModel(new FormData(event.currentTarget)); }}>
            <div className="system-security-note"><Settings2 size={17} /><div><strong>{format("labelProviderProfile", { provider: modelProviderDraft })}</strong><p>{t(providerHelpKey(modelProviderDraft))} {providerNeedsCredential(modelProviderDraft) ? t("systemProviderRequiresCredential") : t("systemProviderCredentialOptional")}</p></div></div>
            <div className="identity-form-grid">
              <label><span>{t("systemName")}</span><input defaultValue={modal.model?.name ?? ""} name="name" required /></label>
              <label><span>{t("systemModelType")}</span><select disabled={Boolean(modal.model)} name="model_type" onChange={(event) => setModelTypeDraft(event.target.value)} value={modelTypeDraft}><option value="Chat">{t("labelChat")}</option><option>Embedding</option><option>OCR</option><option>Judge</option></select>{modal.model ? <input name="model_type" type="hidden" value={modal.model.type} /> : null}</label>
              <label><span>{t("labelProvider")}</span><select name="provider" onChange={(event) => setModelProviderDraft(event.target.value)} value={modelProviderDraft}>{aiProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
              <label><span>{t("labelModelName")}</span><input defaultValue={modelConfigValue(modal.model, "model_name")} name="model_name" placeholder={modelProviderDraft === "Ollama" ? "llama3.1" : modelProviderDraft === "Gemini" ? "gemini-1.5-pro" : modelProviderDraft === "Claude" ? "claude-3-5-sonnet-latest" : t("systemModelNamePlaceholder")} required={modelProviderDraft !== "Custom"} /></label>
            </div>
            {modelProviderDraft === "OpenAI" ? <div className="identity-form-grid">
              <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "https://api.openai.com/v1")} name="base_url" /></label>
              <label><span>{t("systemOrganizationIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "organization_id")} name="organization_id" /></label>
              <label><span>{t("systemProjectIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "project_id")} name="project_id" /></label>
              <OpenAiApiModeField existingMode={modelConfigValue(modal.model, "api_mode")} isExisting={Boolean(modal.model)} modelType={modelTypeDraft} />
              {modelTypeDraft === "Embedding" ? <label><span>{t("systemEmbeddingDimensionOptional")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_dimension")} min={1} name="embedding_dimension" type="number" /></label> : null}
            </div> : null}
            {modelProviderDraft === "Gemini" ? <div className="identity-form-grid"><label><span>{t("labelApiVersion")}</span><input defaultValue={modelConfigValue(modal.model, "api_version", "v1beta")} name="api_version" /></label></div> : null}
            {modelProviderDraft === "Claude" ? <div className="identity-form-grid">
              <label><span>{t("systemBaseUrlOptional")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "")} name="base_url" placeholder="https://api.anthropic.com" /></label>
              <label><span>Anthropic-Version</span><input defaultValue={modelConfigValue(modal.model, "anthropic_version", "2023-06-01")} name="anthropic_version" /></label>
            </div> : null}
            {modelProviderDraft === "Ollama" ? <div className="identity-form-grid">
              <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "http://127.0.0.1:11434")} name="base_url" required /></label>
              <label><span>{t("labelTimeoutSeconds")}</span><input defaultValue={modelConfigValue(modal.model, "timeout_seconds", "120")} min={1} name="timeout_seconds" type="number" /></label>
            </div> : null}
            {modelProviderDraft === "vLLM" ? <div className="identity-form-grid">
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
                {(modelTypeDraft === "Chat" || modelTypeDraft === "Judge") ? <>
                  <label><span>{t("systemModelInputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "input_cost_per_million_tokens")} min="0" name="input_cost_per_million_tokens" step="any" type="number" /></label>
                  <label><span>{t("systemModelOutputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "output_cost_per_million_tokens")} min="0" name="output_cost_per_million_tokens" step="any" type="number" /></label>
                </> : null}
                {modelTypeDraft === "Embedding" ? <label><span>{t("systemModelEmbeddingPrice")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_cost_per_million_tokens")} min="0" name="embedding_cost_per_million_tokens" step="any" type="number" /></label> : null}
                {modelTypeDraft === "OCR" ? <>
                  <label><span>{t("systemModelOcrPagePrice")}</span><input defaultValue={modelConfigValue(modal.model, "ocr_cost_per_page")} min="0" name="ocr_cost_per_page" step="any" type="number" /></label>
                  <label><span>{t("systemModelOcrImagePrice")}</span><input defaultValue={modelConfigValue(modal.model, "ocr_cost_per_image")} min="0" name="ocr_cost_per_image" step="any" type="number" /></label>
                </> : null}
                <label><span>{t("systemModelCostCurrency")}</span><select defaultValue={modelConfigValue(modal.model, "cost_currency")} name="cost_currency"><option value="">{t("systemModelCostCurrencyPlaceholder")}</option>{["TWD", "USD", "JPY", "EUR", "GBP", "CNY", "HKD", "SGD", "AUD", "CAD", "KRW"].map((currency) => <option key={currency}>{currency}</option>)}</select></label>
              </div>
            </div>
            <label><span>{t("systemApiKeyRetainExisting")}</span><input autoComplete="new-password" disabled={modelCredentialClearDraft} name="api_key" type="password" /></label>
            <label><span>{t("labelSecretReference")}</span><input defaultValue={modal.model?.raw?.api_key_secret_ref ?? ""} disabled={modelCredentialClearDraft} name="api_key_secret_ref" placeholder={t("systemSecretReferencePlaceholder")} /></label>
            <AIModelCredentialClearControl clearDraft={modelCredentialClearDraft} configured={Boolean(modal.model?.raw?.api_key_configured)} confirmation={modelCredentialClearConfirmation} modelName={modal.model?.name ?? ""} onClearChange={(checked) => { setModelCredentialClearDraft(checked); setModelCredentialClearConfirmation(""); }} onConfirmationChange={setModelCredentialClearConfirmation} />
            <label><span>{t("systemAdvancedConfigJson")}</span><textarea defaultValue={JSON.stringify(modal.model?.raw?.config ?? {}, null, 2)} name="config_advanced" rows={5} /><small>{t("systemAdvancedConfigHelp")}</small></label>
            <label className="identity-toggle"><input defaultChecked={modal.model?.status !== "inactive"} name="is_active" type="checkbox" /><span>{t("systemEnable")}</span></label>
            <label className="identity-toggle"><input defaultChecked={modal.model?.default ?? false} name="is_default" type="checkbox" /><span>{t("systemSetTypeDefault")}</span></label>
            <footer><button className="action-button secondary" onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={submitting || (!modal.model && !canCreateModels) || (Boolean(modal.model) && !canEditModels) || (modelCredentialClearDraft && modelCredentialClearConfirmation !== modal.model?.name)} type="submit">{modal.model ? <Save size={16} /> : <Plus size={16} />}{modal.model ? t("systemSaveModel") : t("systemAddModel")}</button></footer>
          </form> : null}
          {modal.type === "model-delete" ? <div className="system-crud-form model-delete-content">
            <div className="model-delete-warning"><AlertTriangle size={20} /><div><strong>{t("systemDeleteModelWarningTitle")}</strong><p>{t("systemDeleteModelWarningHelp")}</p></div></div>
            <div className="system-detail-grid"><div><small>{t("systemModel")}</small><strong>{modal.model.name}</strong></div><div><small>{t("systemModelType")}</small><strong>{modal.model.type}</strong></div><div><small>{t("labelProvider")}</small><strong>{modal.model.provider}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.model.status)}</strong></div></div>
            {modelDeleteDependencies.length ? <section className="model-delete-dependencies"><strong>{t("systemDeleteModelBlockedTitle")}</strong><p>{t("systemDeleteModelBlockedHelp")}</p><ul>{modelDeleteDependencies.map((dependency) => <li key={dependency.type}><span>{modelDeleteDependencyLabel(dependency.type)}</span><strong>{dependency.count}</strong></li>)}</ul></section> : null}
            <label><span>{format("systemDeleteModelConfirmationLabel", { name: modal.model.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setModelDeleteConfirmation(event.target.value)} placeholder={modal.model.name} value={modelDeleteConfirmation} /><small>{t("systemDeleteModelConfirmationHelp")}</small></label>
            <footer><button className="action-button secondary" disabled={submitting} onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modelDeleteConfirmation !== modal.model.name} onClick={() => { void submitModelDelete(modal.model); }} type="button"><Trash2 size={16} />{t("systemDeleteModelPermanently")}</button></footer>
          </div> : null}
          {modal.type === "api-key-create" ? <form className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void submitApiKey(new FormData(event.currentTarget)); }}>
            <p className="system-modal-help">{t("systemApiKeyCreateHelp")}</p>
            <div className="identity-form-grid">
              <label><span>{t("systemName")}</span><input name="name" placeholder={t("systemApiKeyNamePlaceholder")} required /></label>
              <label><span>{t("systemApiKeyRequestsPerMinute")}</span><input defaultValue={60} min={1} name="requests_per_minute" type="number" /></label>
              <label><span>{t("systemApiKeyValidFrom")}</span><input name="valid_from" type="datetime-local" /></label>
              <label><span>{t("systemApiKeyExpiresAt")}</span><input name="expires_at" type="datetime-local" /></label>
              <label><span>{t("systemApiKeyContactName")}</span><input name="contact_name" /></label>
              <label><span>{t("systemApiKeyContactEmail")}</span><input name="contact_email" type="email" /></label>
              <label><span>{t("systemApiKeyContactDepartment")}</span><input name="contact_department" /></label>
              <label className="identity-wide-field"><span>{t("systemDescription")}</span><textarea name="description" rows={3} /></label>
            </div>
            <div className="system-api-project-picker"><strong>{t("systemApiKeyProjectScopes")}</strong><p>{t("systemApiKeyProjectScopesHelp")}</p>{activeProjects.length ? <div>{activeProjects.map((project) => <label className={apiKeyProjectDraft.includes(project.id) ? "active" : ""} key={project.id}><input checked={apiKeyProjectDraft.includes(project.id)} onChange={(event) => toggleApiKeyProjectDraft(project.id, event.target.checked)} type="checkbox" /> <span>{project.name}</span></label>)}</div> : <EmptyInlineState>{t("systemApiKeyNoProjects")}</EmptyInlineState>}</div>
            <footer><button className="action-button secondary" disabled={submitting} onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={!canCreateSystemManagement || submitting || !apiKeyProjectDraft.length} type="submit"><Plus size={16} />{t("systemApiKeyCreate")}</button></footer>
          </form> : null}
          {modal.type === "api-key-manage" ? <form className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void saveApiKeyManagement(modal.client, new FormData(event.currentTarget)); }}>
            <div className="system-security-note"><KeyRound size={17} /><div><strong>{format("systemApiKeyVersionIdentity", { prefix: modal.client.api_key_prefix, version: modal.client.api_key_version })}</strong><p>{t("systemApiKeyManageHelp")}</p></div><StateBadge tone={apiKeyStatusTone(modal.client)}>{apiKeyStatusLabel(modal.client)}</StateBadge></div>
            <div className="identity-form-grid">
              <label><span>{t("systemName")}</span><input defaultValue={modal.client.name} disabled={modal.client.status === "revoked"} name="name" required /></label>
              <label><span>{t("systemApiKeyRequestsPerMinute")}</span><input defaultValue={modal.client.requests_per_minute ?? 60} disabled={modal.client.status === "revoked"} min={1} name="requests_per_minute" type="number" /></label>
              <label><span>{t("systemApiKeyValidFrom")}</span><input defaultValue={apiDateInputValue(modal.client.valid_from)} disabled={modal.client.status === "revoked"} name="valid_from" type="datetime-local" /></label>
              <label><span>{t("systemApiKeyExpiresAt")}</span><input defaultValue={apiDateInputValue(modal.client.expires_at)} disabled={modal.client.status === "revoked"} name="expires_at" type="datetime-local" /></label>
              <label><span>{t("systemApiKeyContactName")}</span><input defaultValue={modal.client.contact_name ?? ""} disabled={modal.client.status === "revoked"} name="contact_name" /></label>
              <label><span>{t("systemApiKeyContactEmail")}</span><input defaultValue={modal.client.contact_email ?? ""} disabled={modal.client.status === "revoked"} name="contact_email" type="email" /></label>
              <label><span>{t("systemApiKeyContactDepartment")}</span><input defaultValue={modal.client.contact_department ?? ""} disabled={modal.client.status === "revoked"} name="contact_department" /></label>
              <label className="identity-wide-field"><span>{t("systemDescription")}</span><textarea defaultValue={modal.client.description ?? ""} disabled={modal.client.status === "revoked"} name="description" rows={3} /></label>
            </div>
            <div className="system-api-project-picker"><strong>{t("systemApiKeyProjectScopes")}</strong><p>{t("systemApiKeyProjectScopesHelp")}</p>{activeProjects.length ? <div>{activeProjects.map((project) => {
              const scopeDraft = apiKeyScopeDrafts[modal.client.id] ?? modal.client.project_ids;
              return <label className={scopeDraft.includes(project.id) ? "active" : ""} key={project.id}><input checked={scopeDraft.includes(project.id)} disabled={modal.client.status === "revoked" || !canEditSystemManagement || submitting} onChange={(event) => toggleApiKeyScopeDraft(modal.client.id, project.id, event.target.checked)} type="checkbox" /> <span>{projectNameById.get(project.id) ?? project.name}</span></label>;
            })}</div> : <EmptyInlineState>{t("systemApiKeyNoProjects")}</EmptyInlineState>}</div>
            <div className="system-api-key-modal-actions">
              <button className="icon-text-button" disabled={modal.client.status === "revoked" || !canEditSystemManagement || submitting} onClick={() => { void rotateApiKey(modal.client); }} type="button"><RotateCcw size={15} />{t("systemApiKeyRotate")}</button>
              {modal.client.status === "active" ? <button className="icon-text-button" disabled={!canEditSystemManagement || submitting} onClick={() => { void setApiKeyStatus(modal.client, false); }} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={modal.client.status === "revoked" || !canEditSystemManagement || modal.client.effective_status === "expired" || submitting} onClick={() => { void setApiKeyStatus(modal.client, true); }} type="button">{t("systemEnable")}</button>}
              <button className="icon-text-button danger" disabled={modal.client.status === "revoked" || !canDeleteSystemManagement || submitting} onClick={() => setModal({ type: "confirm", title: t("systemApiKeyRevoke"), message: format("systemApiKeyRevokeConfirm", { name: modal.client.name }), actionLabel: t("systemApiKeyRevoke"), run: () => revokeApiKey(modal.client) })} type="button">{t("systemApiKeyRevoke")}</button>
            </div>
            <footer><button className="action-button secondary" disabled={submitting} onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button" disabled={!canEditSystemManagement || submitting || modal.client.status === "revoked"} type="submit"><Save size={16} />{t("save")}</button></footer>
          </form> : null}
          {modal.type === "confirm" ? <div className="system-crud-form"><p>{localize(modal.message)}</p><footer><button className="action-button secondary" disabled={submitting} onClick={() => setModal(null)} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting} onClick={async () => { setSubmitting(true); setModalError(""); try { await modal.run(); setModal(null); } catch (caught) { setModalError(errorMessage(caught as ApiError | Error)); } finally { setSubmitting(false); } }} type="button">{localize(modal.actionLabel)}</button></footer></div> : null}
        </section>
      </div> : null}
    </section>
  );
}
