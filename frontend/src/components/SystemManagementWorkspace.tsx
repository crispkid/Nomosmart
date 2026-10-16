"use client";

import { IntegrationClientDateError, integrationClientDateInput, integrationClientDateUpdate, integrationClientDateValue } from "@/lib/integrationClientDates";
import { UiValidationError, MutationOutcomeUnknown } from "@/lib/transportError";
import { useOperationGuard } from "./useOperationGuard";
import { FeedbackForm } from "@/components/FeedbackForm";
import { FeedbackConfirm } from "./FeedbackConfirm";
import { useFeedback } from "./FeedbackProvider";
import { FeedbackMessage, FeedbackField } from "@/components/FeedbackMessage";
import { formatCount } from "@/lib/numberFormat";
import type { FeedbackTone } from "@/lib/feedback";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
  listModels,
  listModelsPage,
  listRoles,
  listUsersPage,
  listRolesPage,
  listProjectsPage,
  listIntegrationClientsPage,
  getUser,
  getRole,
  getIntegrationClient,
  getProject,
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
  userRow, roleRow, roleMemberCounts, type UserRow, type RoleRow,
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
import { formatPersonName } from "@/lib/personName";
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
type SystemReadState = { scope: string; phase: "loading" | "ready" | "error" | "forbidden"; received: boolean; error?: ApiError | Error };
type RoleStatusFilter = "all" | "enabled" | "disabled";
type GroupMappingRow = { groupId: string; roleId: string; group: string; source: string; role: string; members: number | null };
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
  | { type: "confirm"; title: string; message: string; actionLabel: string; successTitle?: TranslationKey; target: { kind: "user" | "role" | "model" | "client"; id: string; expected?: { field: "is_active" | "status"; value: boolean | string } }; run: (accepted: () => void, current: () => boolean) => Promise<void> };

function modalScope(modal: ModalState | null) {
  if (!modal) return "closed";
  if (modal.type === "confirm") return `${modal.type}:${modal.target.kind}:${modal.target.id}`;
  if ("role" in modal) return `${modal.type}:${modal.role?.id ?? "new"}`;
  if ("model" in modal) return `${modal.type}:${modal.model?.id ?? "new"}`;
  if ("user" in modal) return `${modal.type}:${modal.user.id}`;
  if ("client" in modal) return `${modal.type}:${modal.client.id}`;
  return modal.type;
}

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
  const { apiFetch, can, currentUser, operationGuards } = useAuth();
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
  const [apiKeyDateValidation, setApiKeyDateValidation] = useState<{ scope: string; errors: Partial<Record<"valid_from" | "expires_at", TranslationKey>> }>({ scope: "", errors: {} });
  const [apiKeyProjectDraft, setApiKeyProjectDraft] = useState<string[]>([]);
  const [apiKeyScopeDrafts, setApiKeyScopeDrafts] = useState<Record<string, string[]>>({});
  const [apiKeyOneTime, setApiKeyOneTime] = useState<{ name: string; key: string } | null>(null);
  const [selectedPromptId, setSelectedPromptId] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [promptDraftSourceVersion, setPromptDraftSourceVersion] = useState<number | null>(null);
  const [promptModelDraft, setPromptModelDraft] = useState("");
  const [promptNotice, setPromptNotice] = useState<{ message: string; tone: FeedbackTone } | null>(null);
  const promptMessage = promptNotice?.message ?? "";
  const setPromptMessage = useCallback((message: string, tone: FeedbackTone = "info") => setPromptNotice(message ? { message, tone } : null), []);
  const [promptError, setPromptError] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);
  const [promptEditorPrompt, setPromptEditorPrompt] = useState<PromptRow | null>(null);
  const [promptBaseline, setPromptBaseline] = useState("");
  const [promptLeave, setPromptLeave] = useState<(() => void) | null>(null);
  const promptDialogRef = useRef<HTMLElement>(null);
  const promptFocusRef = useRef<HTMLElement | null>(null);
  const promptReceipt = useRef<PromptRow | null>(null);
  const promptMutationScope = useRef<string | null>(null);
  const promptIntent = useRef<{ kind: "save" | "active" | "create"; id?: string; active?: boolean; content?: string } | null>(null);
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
  const [loadedSystemScope, setLoadedSystemScope] = useState("");
  const [sectionReads, setSectionReads] = useState<Record<string, SystemReadState>>({});
  const [systemLoading, setSystemLoading] = useState(true);
  const [systemError, setSystemError] = useState<ApiError | Error | null>(null);
  const [quickError, setQuickError] = useState<ApiError | Error | null>(null);
  const [quickQueryFailed, setQuickQueryFailed] = useState(false);
  const { notify } = useFeedback();
  const [modal, setModalState] = useState<ModalState | null>(null);
  const [dirtyModal, setDirtyModal] = useState<ModalState | null>(null);
  const [discardModal, setDiscardModal] = useState<ModalState | null>(null);
  const systemDialogRef = useRef<HTMLElement>(null);
  const apiKeyDialogRef = useRef<HTMLElement>(null);
  const systemDialogTriggerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const remember = (event: FocusEvent) => { if (event.target instanceof HTMLElement && !event.target.closest('[role="dialog"],[role="alertdialog"]')) systemDialogTriggerRef.current = event.target; };
    document.addEventListener("focusin", remember);
    return () => document.removeEventListener("focusin", remember);
  }, []);
  useEffect(() => {
    if (!modal) return;
    const dialog = systemDialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) dialog.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const trigger = systemDialogTriggerRef.current;
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, [modal]);
  useEffect(() => {
    if (!apiKeyOneTime || modal) return;
    const trigger = systemDialogTriggerRef.current;
    const fallback = tabRefs.current.find(button => button?.getAttribute("aria-selected") === "true") ?? tabRefs.current[0];
    apiKeyDialogRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [apiKeyOneTime, modal, activeTab]);
  useEffect(() => {
    if (!promptEditorOpen) return;
    const trigger = systemDialogTriggerRef.current;
    const fallback = tabRefs.current.find(button => button?.getAttribute("aria-selected") === "true") ?? tabRefs.current[0];
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [promptEditorOpen]);
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
  const [modelDeleteConfirmation, setModelDeleteConfirmation] = useState("");
  const [modelDeleteDependencies, setModelDeleteDependencies] = useState<ModelDeleteDependency[]>([]);
  const [modelProviderDraft, setModelProviderDraft] = useState("OpenAI");
  const [modelTypeDraft, setModelTypeDraft] = useState("Chat");
  const [modelPairDraft, setModelPairDraft] = useState<string[]>([]);
  const [modelCredentialClearDraft, setModelCredentialClearDraft] = useState(false);
  const [modelCredentialClearConfirmation, setModelCredentialClearConfirmation] = useState("");
  const [userTableIds, setUserTableIds] = useState<string[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [userOverallTotal, setUserOverallTotal] = useState<number | null>(null);
  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(20);
  const [roleTableIds, setRoleTableIds] = useState<string[]>([]);
  const [roleTotal, setRoleTotal] = useState(0);
  const [roleOverallTotal, setRoleOverallTotal] = useState<number | null>(null);
  const [rolePage, setRolePage] = useState(1);
  const [rolePageSize, setRolePageSize] = useState(20);
  const [clientQuery, setClientQuery] = useState("");
  const [clientCursors, setClientCursors] = useState<(string | undefined)[]>([undefined]);
  const [clientPageSize, setClientPageSize] = useState(20);
  const [clientNextCursor, setClientNextCursor] = useState<string | null>(null);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectOffset, setProjectOffset] = useState(0);
  const [projectTotal, setProjectTotal] = useState(0);
  const [projectCandidateIds, setProjectCandidateIds] = useState<string[]>([]);
  const [memberOffset, setMemberOffset] = useState(0);
  const [memberTotal, setMemberTotal] = useState(0);
  const [memberCandidateIds, setMemberCandidateIds] = useState<string[]>([]);
  const [roleUsersReadback, setRoleUsersReadback] = useState<RoleUsersResponse | null>(null);
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
  const [ocrSettingsHash, setOcrSettingsHash] = useState<string | null>(null);
  const [ocrDefaults, setOcrDefaults] = useState<{ ocr_page_max_output_tokens: number; ocr_document_max_tokens: number } | null>(null);
  const [savedParameters, setSavedParameters] = useState(defaultSystemParameters);
  const [parameterErrors, setParameterErrors] = useState(validateSystemParameters(defaultSystemParameters));
  const [parameterNotice, setParameterNotice] = useState<{ message: string; tone: FeedbackTone } | null>(null);
  const parameterMessage = parameterNotice?.message ?? "";
  const setParameterMessage = useCallback((message: string, tone: FeedbackTone = "error") => setParameterNotice(message ? { message, tone } : null), []);
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
      notify({ id: crypto.randomUUID(), scope: "system", tone: "success", title: "feedbackConnectionVerified" });
    } catch (caught) {
      setSystemError(caught as ApiError | Error);
    }
  }
  const localizedBreakGlassStatus = (status?: BreakGlassStatusResponse["status"]) => {
    if (!sectionReady("breakGlass")) return t("systemReadCountUnknown");
    if (status === "configured_disabled") return t("identityBreakGlassConfiguredDisabled");
    if (status === "attention_required") return t("identityNeedsAttention");
    if (status === "unavailable") return t("systemOpUnavailable");
    return t("systemNotConfigured");
  };
  const activeEmbeddingModels = liveModels.filter((model) => model.type === "Embedding" && model.status === "active");

  const systemReadScope = `${currentUser?.user_id}:${JSON.stringify(currentUser?.permissions ?? [])}`;
  const systemReadScopeRef = useRef<string | null>(systemReadScope);
  const systemReadEpoch = useRef({ version: 0 });
  const systemReadVersions = useRef<Record<string, number>>({});
  const systemReadStates = useRef<Record<string, SystemReadState>>({});
  const mappingRows = useRef<Awaited<ReturnType<typeof listExternalGroupMappings>>>([]);
  const groupRows = useRef<ExternalGroupResponse[]>([]);
  const roleNames = useRef(new Map<string, string>());
  const draftStates = useRef({ prompts: false, parameters: false, identity: false });
  useLayoutEffect(() => {
    const epoch = systemReadEpoch.current;
    systemReadScopeRef.current = systemReadScope; epoch.version++;
    systemReadStates.current = {}; mappingRows.current = []; groupRows.current = []; roleNames.current = new Map();

    return () => { systemReadScopeRef.current = null; epoch.version++; };
  }, [systemReadScope]);
  useLayoutEffect(() => {
    draftStates.current = { prompts: promptEditorOpen || promptDraft !== promptBaseline, parameters: JSON.stringify(parameters) !== JSON.stringify(savedParameters), identity: identityUnlocked || JSON.stringify(identitySettings) !== JSON.stringify(savedIdentitySettings) };
  }, [promptEditorOpen, promptDraft, promptBaseline, parameters, savedParameters, identityUnlocked, identitySettings, savedIdentitySettings]);

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
  function cacheUsers(rows: UserSummary[]) {
    setLiveUsers(current => {
      const map = new Map(current.map(row => [row.id, row]));
      rows.forEach(user => map.set(user.id, userRow(user)));
      return [...map.values()];
    });
  }
  function cacheRoles(rows: RoleResponse[]) {
    rows.forEach(role => roleNames.current.set(role.id, role.name));
    setLiveRoles(current => {
      const map = new Map(current.map(row => [row.id, row]));
      rows.forEach(role => map.set(role.id, roleRow(role, map.get(role.id))));
      return [...map.values()];
    });
  }
  function cacheProjects(rows: ProjectResponse[]) { setLiveProjects(current => [...new Map([...current, ...rows].map(row => [row.id, row])).values()]); }
  function applyMemberSnapshot(roleId: string, response: RoleUsersResponse) {
    setLiveRoles(rows => rows.map(row => row.id === roleId ? { ...row, ...roleMemberCounts(response), lockVersion: response.lock_version } : row));
  }
  function updateMappingProjection() {
    const known = systemReadStates.current.mappings?.scope === systemReadScope && systemReadStates.current.mappings?.phase === "ready";
    setLiveRoles(current => current.map(role => {
      const mapping = mappingRows.current.find(row => row.role_id === role.id);
      return { ...role, groups: known ? (mapping ? 1 : 0) : null, mappingGroupId: known ? mapping?.external_group_id ?? null : role.mappingGroupId };
    }));
    const groups = new Map(groupRows.current.map(group => [group.id, group]));
    setLiveGroupMappings(mappingRows.current.map(mapping => ({ groupId: mapping.external_group_id, roleId: mapping.role_id, group: groups.get(mapping.external_group_id)?.path || groups.get(mapping.external_group_id)?.group_name || mapping.external_group_id, source: groups.get(mapping.external_group_id)?.identity_origin || "keycloak_local", role: roleNames.current.get(mapping.role_id) ?? mapping.role_id, members: groups.get(mapping.external_group_id)?.member_count ?? null })));
  }
  async function readRoleMembers(role: Pick<RoleRow, "id">, current: () => boolean = () => true) {
    setLiveRoles(rows => rows.map(row => row.id === role.id ? { ...row, members: null, manualMembers: null, ldapMembers: null, breakGlassMembers: null } : row));
    return readSystemSection(`members:${role.id}`, () => getRoleUsers(apiFetch, role.id), response => {
      setLiveRoles(rows => rows.map(row => row.id === role.id ? { ...row, ...roleMemberCounts(response) } : row));
    }, current);
  }
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
      case "parameters": return readSystemSection(section, () => getSystemParameters(apiFetch), payload => {
        if (draftStates.current.parameters) return;
        const values = { uploadLimitMb: payload.max_upload_size_mb, timezone: payload.default_timezone, stagingTtlDays: payload.staging_index_ttl_days, sessionDraftTtlMinutes: payload.session_expired_form_draft_ttl_minutes, ocrPageOutputTokens: payload.ocr_page_max_output_tokens, ocrDocumentOutputTokens: payload.ocr_document_max_tokens };
        setOcrSettingsHash(payload.ocr_token_settings_hash); setOcrDefaults(payload.ocr_token_defaults);
        setParameters(values); setSavedParameters(values); setParameterErrors(validateSystemParameters(values));
      }, current);
      case "identity": return readSystemSection(section, () => getIdentitySettings(apiFetch), identityPayload => {
        if (draftStates.current.identity) return;
        const identityFromApi = identitySettingsFromConfiguration(identityPayload.configuration);
        setIdentitySettings(identityFromApi); setSavedIdentitySettings(identityFromApi); setIdentityErrors(validateIdentitySettings(identityFromApi));
        setIdentityConfigurationSource(identityPayload.configuration_source); setIdentitySecretConfigured(identityPayload.secret_configured);
      }, current);
      case "providers": return readSystemSection(section, () => listDirectoryProviders(apiFetch), rows => { setDirectoryProviders(rows); setDirectoryProviderError(""); setDirectoryFilterDrafts(Object.fromEntries(rows.map(row => [row.id, row.custom_user_search_filter]))); }, current);
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
    setUserTableIds([]); setRoleTableIds([]); setProjectCandidateIds([]); setMemberCandidateIds([]);
    setUserOverallTotal(null); setRoleOverallTotal(null); setSelectedRole("");
    setUserPage(1); setRolePage(1); setClientCursors([undefined]); setProjectOffset(0); setMemberOffset(0);
    }
    setSystemLoading(true); setSystemError(null);
    await Promise.all(["users", "roles", "models", "prompts", "projects", "clients", "syncRuns", "parameters", "identity", "providers", "groups", "mappings", "breakGlass", "status"].map(section => reloadSystemSection(section)));
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
  }, [canViewSystemManagement, systemReadScope]); // eslint-disable-line react-hooks/exhaustive-deps

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
      setParameterMessage(t("systemParametersDraftRestored"), "info");
    };
    window.addEventListener("nomosmart:restore-session-draft", restore);
    return () => window.removeEventListener("nomosmart:restore-session-draft", restore);
  }, [parameters, t, setParameterMessage]);

  useEffect(() => {
    if (!canViewSystemManagement) return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("users"); }, 300);
    return () => { clearTimeout(timer); versions.users = (versions.users ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, userQuery, userSourceFilter, userPage, userPageSize]);
  useEffect(() => {
    if (!canViewSystemManagement) return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("roles"); }, 300);
    return () => { clearTimeout(timer); versions.roles = (versions.roles ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, roleQuery, roleStatusFilter, rolePage, rolePageSize]);
  useEffect(() => {
    if (!canViewSystemManagement) return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("clients"); }, 300);
    return () => { clearTimeout(timer); versions.clients = (versions.clients ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, clientQuery, clientCursors, clientPageSize]);
  useEffect(() => {
    if (!canViewSystemManagement) return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("projects"); }, 300);
    return () => { clearTimeout(timer); versions.projects = (versions.projects ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, projectQuery, projectOffset]);
  useEffect(() => {
    if (!canViewSystemManagement || modal?.type !== "role-users") return;
    const versions = systemReadVersions.current;
    const timer = setTimeout(() => { void reloadSystemSection("memberCandidates"); }, 300);
    return () => { clearTimeout(timer); versions.memberCandidates = (versions.memberCandidates ?? 0) + 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiFetch, systemReadScope, canViewSystemManagement, modal?.type, modal?.type === "role-users" ? modal.role.id : null, roleUserSearch, memberOffset]);
  function renderListPager(section: string, page: number, size: number, total: number | null, previous: () => void, next: (() => void) | null, changeSize: (size: number) => void) {
    const busy = !sectionReady(section);
    return <div className="model-list-pagination"><label><span>{t("systemRowsPerPage")}</span><select aria-label={t("systemRowsPerPage")} disabled={busy} onChange={event => changeSize(Number(event.target.value))} value={size}>{[20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</select></label><span>{total === null ? format("adminListBatch", { page: formatCount(page, locale) }) : format("systemPageOf", { page: formatCount(page, locale), total: formatCount(Math.max(1, Math.ceil(total / size)), locale) })}</span><div><button className="action-button secondary" disabled={busy || page <= 1} onClick={previous} type="button"><ChevronLeft size={15} />{t("adminPrevious")}</button><button className="action-button secondary" disabled={busy || !next} onClick={next ?? undefined} type="button">{t("adminNext")}<ChevronRight size={15} /></button></div></div>;
  }
  function renderProjectSearch() { return <><label className="system-toolbar"><Search size={16} /><input aria-label={t("adminSearchProjects")} maxLength={100} onChange={event => { setProjectQuery(event.target.value); setProjectOffset(0); }} placeholder={t("adminSearchProjects")} value={projectQuery} /></label><span>{format("adminSelectedCount", { count: formatCount(modal?.type === "api-key-manage" ? (apiKeyScopeDrafts[modal.client.id] ?? modal.client.project_ids).length : apiKeyProjectDraft.length, locale) })}</span>{projectCandidateIds.length < projectTotal ? <button className="action-button secondary" disabled={!sectionReady("projects")} onClick={() => setProjectOffset(offset => offset + 20)} type="button">{t("adminLoadMore")}</button> : null}</>; }

  const remainingIdentitySeconds = identityUnlockExpiresAt ? Math.max(0, Math.ceil((identityUnlockExpiresAt - identityNow) / 1000)) : 0;
  const remainingIdentityTime = `${String(Math.floor(remainingIdentitySeconds / 60)).padStart(2, "0")}:${String(remainingIdentitySeconds % 60).padStart(2, "0")}`;
  const identityReauthBusy = identityReauthStatus === "opening" || identityReauthStatus === "completing";
  const userRowName = (user: UserRow) => formatPersonName(user.raw ?? { display_name: user.name }, locale) || user.name;
  const filteredUsers = userTableIds.flatMap(id => liveUsers.find(row => row.id === id) ?? []);
  const filteredLocalRoles = roleTableIds.flatMap(id => liveRoles.find(row => row.id === id) ?? []);
  const roleUserRows = roleUsers?.users ?? [];
  const originalManualRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "manual").map((row) => row.user_id));
  const externalRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "external_sync").map((row) => row.user_id));
  const breakGlassRoleUserIds = new Set(roleUserRows.filter((row) => row.source === "break_glass").map((row) => row.user_id));
  const draftRoleUserIds = new Set(roleUserDraftIds);
  const activeRoleUserCandidates = liveUsers.filter((user) => user.status === "active" && memberCandidateIds.includes(user.id));
  const filteredRoleUserCandidates = activeRoleUserCandidates;
  const pendingAddUsers = liveUsers.filter((user) => user.status === "active" && draftRoleUserIds.has(user.id) && !originalManualRoleUserIds.has(user.id));
  const pendingRemoveUsers = liveUsers.filter((user) => originalManualRoleUserIds.has(user.id) && !draftRoleUserIds.has(user.id));
  const activeProjects = projectCandidateIds.flatMap(id => liveProjects.find(project => project.id === id && project.status === "active") ?? []);
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
    if (!liveReady || !ocrSettingsHash || !canEditParameters) return;
    const errors = validateSystemParameters(parameters);
    setParameterErrors(errors);
    if (hasParameterErrors(errors)) return;
    try {
      const saved = await updateSystemParameters(apiFetch, { max_upload_size_mb: parameters.uploadLimitMb, default_timezone: parameters.timezone, staging_index_ttl_days: parameters.stagingTtlDays, session_expired_form_draft_ttl_minutes: parameters.sessionDraftTtlMinutes, ocr_page_max_output_tokens: parameters.ocrPageOutputTokens!, ocr_document_max_tokens: parameters.ocrDocumentOutputTokens!, expected_ocr_token_settings_hash: ocrSettingsHash });
      const next = { uploadLimitMb: saved.max_upload_size_mb, timezone: saved.default_timezone, stagingTtlDays: saved.staging_index_ttl_days, sessionDraftTtlMinutes: saved.session_expired_form_draft_ttl_minutes, ocrPageOutputTokens: saved.ocr_page_max_output_tokens, ocrDocumentOutputTokens: saved.ocr_document_max_tokens };
      setOcrSettingsHash(saved.ocr_token_settings_hash); setOcrDefaults(saved.ocr_token_defaults);
      setSavedParameters(next);
      setParameters(next);
      setParameterMessage(t("systemParametersSaved"), "success");
    } catch (caught) {
      setParameterMessage(errorMessage(caught as ApiError | Error));
    }
  }

  function restoreParameters() {
    if (!liveReady || !ocrDefaults || !canEditParameters) return;
    setParameters({ ...defaultSystemParameters, ocrPageOutputTokens: ocrDefaults.ocr_page_max_output_tokens, ocrDocumentOutputTokens: ocrDefaults.ocr_document_max_tokens });
    setParameterErrors({});
    setParameterMessage(t("systemParametersDefaultsRestored"), "success");
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

  async function refreshRolesAndMappings(current: () => boolean = () => true) {
    const results = await Promise.all(["roles", "groups", "mappings"].map(section => reloadSystemSection(section, current)));
    if (current() && results.some(value => !value)) throw new Error("System read could not be confirmed");
  }

  async function refreshIdentityData() {
    const success = await reloadSystemSection("users");
    await refreshRolesAndMappings();
    if (!success) throw new Error("System read could not be confirmed");
  }

  async function refreshModels(current: () => boolean = () => true) {
    const success = await reloadSystemSection("models", current);
    if (current() && !success) throw new Error("System read could not be confirmed");
    if (current()) await refreshModelTable();
  }

  async function refreshPrompts(current: () => boolean = () => true) {
    const success = await reloadSystemSection("prompts", current);
    if (current() && !success) throw new Error("System read could not be confirmed");
  }

  async function refreshSystemStatus() { await reloadSystemSection("status"); }

  async function refreshIntegrationClients(current?: () => boolean) {
    const valid = current ?? (() => true);
    const success = await reloadSystemSection("clients", valid);
    if (current && valid() && !success) throw new Error("System read could not be confirmed");
  }

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
      setSubmitting(false); setDirtyModal(null); setModal(null);
      notify({ id: modalEventId.current, scope: "system", tone: "success", title });
    } catch (caught) {
      if (!modalGuard.current(token)) return;
      modalGuard.failed(token, caught);
      setModalError(modalGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : errorMessage(caught as ApiError | Error));
    } finally { if (modalGuard.current(token)) setSubmitting(false); }
  }

  async function readOutcomeRecord<T>(read: Promise<T>): Promise<T | undefined> {
    try { return await read; }
    catch (error) { if (error && typeof error === "object" && "status" in error && error.status === 404) return undefined; throw error; }
  }

  async function queryModalOutcome() {
    const token = modalGuard.beginCheck(); if (token === null || !modal) return;
    setModalQueryMessage(t("feedbackCheckingOutcome"));
    try {
      const kind = modal.type === "confirm" ? modal.target.kind : ["model", "model-delete"].includes(modal.type) ? "model" : ["role", "role-delete", "role-users", "mapping"].includes(modal.type) ? "role" : modal.type === "user" ? "user" : "client";
      const sameMutation = modalMutationScope.current === modalGuard.scope;
      const targetId = (modal.type === "confirm" ? modal.target.id : "model" in modal ? modal.model?.id : "role" in modal ? modal.role?.id : "user" in modal ? modal.user.id : "client" in modal ? modal.client.id : undefined) ?? (sameMutation && modalGuard.snapshot().phase !== "unknown" ? modalReceiptId.current : undefined);
      let record: { name?: string; display_name?: string | null; is_active?: boolean; status?: string; lock_version?: number; config_version?: number } | undefined;
      let detailReadback = "";
      if (kind === "model") {
        const rows = await listModels(apiFetch); if (!modalGuard.current(token)) return;
        record = rows.find(row => row.id === targetId);
        setLiveModels(rows.map(modelRow)); setModelTableRows(current => current.map(row => { const found = rows.find(item => item.id === row.id); return found ? modelRow(found) : row; }));
      } else if (targetId && kind === "role") {
        const role = await readOutcomeRecord(getRole(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        if (role && (modal.type === "mapping" || modal.type === "role-users")) {
          const members = await getRoleUsers(apiFetch, targetId); if (!modalGuard.current(token)) return;
          const mappings = modal.type === "mapping" ? await listExternalGroupMappings(apiFetch) : null;
          if (!modalGuard.current(token)) return;
          const currentRole = await getRole(apiFetch, targetId); if (!modalGuard.current(token)) return;
          if (role.lock_version !== members.lock_version || currentRole.lock_version !== members.lock_version) throw new Error("snapshot_changed_reload");
          record = currentRole; cacheRoles([currentRole]); applyMemberSnapshot(targetId, members);
          setRoleUsersReadback(members);
          detailReadback = modal.type === "mapping" ? format("adminMemberReadback", { count: formatCount(new Set(members.users.map(user => user.user_id)).size, locale), version: formatCount(members.lock_version, locale) }) : "";
          if (mappings) {
            mappingRows.current = mappings;
            systemReadVersions.current.mappings = (systemReadVersions.current.mappings ?? 0) + 1;
            setReadState("mappings", { scope: systemReadScope, phase: "ready", received: true });
            updateMappingProjection();
            const id = mappings.find(mapping => mapping.role_id === targetId)?.external_group_id;
            const group = groupRows.current.find(group => group.id === id);
            detailReadback += ` · ${format("adminMappingReadback", { group: group?.path || group?.group_name || id || t("systemNotConfigured") })}`;
          }
        } else if (role) { record = role; cacheRoles([role]); }
      } else if (targetId && kind === "user") {
        const user = await readOutcomeRecord(getUser(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        record = user; if (user) cacheUsers([user]);
      } else if (targetId && kind === "client") {
        const client = await readOutcomeRecord(getIntegrationClient(apiFetch, targetId)); if (!modalGuard.current(token)) return;
        record = client; if (client) setIntegrationClients(rows => rows.map(row => row.id === client.id ? client : row));
      }
      const acknowledged = modalGuard.snapshot().phase === "read_failed" || modalGuard.snapshot().phase === "accepted";
      const expected = modal.type === "confirm" ? modal.target.expected : undefined;
      const currentGoalConfirmed = Boolean(record && expected && record[expected.field] === expected.value);
      if (acknowledged || currentGoalConfirmed) {
        modalGuard.checked(token, true); setModalError(""); setDirtyModal(null); setModal(null);
        notify({ id: sameMutation ? modalEventId.current : crypto.randomUUID(), scope: "system", tone: acknowledged && sameMutation ? "success" : "info", title: acknowledged && sameMutation ? modalSuccess.current : "feedbackCurrentStateChecked" });
      } else {
        modalGuard.checked(token);
        setModalQueryMessage(t("feedbackSystemOutcomeChecked"));
        setModalReadback(record ? [format("feedbackCurrentRecord", { name: record.name ?? record.display_name ?? "—", status: record.is_active !== undefined ? t(record.is_active ? "systemEnabled" : "systemDisabled") : localizedStatus(record.status ?? "unknown"), version: record.config_version ?? record.lock_version ?? "—" }), detailReadback].filter(Boolean).join(" · ") : t("feedbackRecordNotFound"));
      }
    } catch {
      if (!modalGuard.current(token)) return;
      modalGuard.checkFailed(token); setModalQueryMessage(t("feedbackOutcomeQueryFailed"));
    }
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

  async function queryQuickOutcome() {
    const token = quickGuard.beginCheck(); const target = quickTarget.current;
    if (token === null || !target) return;
    setQuickQueryFailed(false);
    try {
      const rows = target.kind === "model" ? await listModels(apiFetch) : await listRoles(apiFetch);
      if (!quickGuard.current(token)) return;
      const row = rows.find(item => item.id === target.id);
      const confirmed = quickGuard.snapshot().phase === "read_failed" || Boolean(row && (target.field === "is_active" ? row.is_active : "is_default" in row && row.is_default) === target.value);
      if (confirmed) {
        if (target.kind === "model") await refreshModels(() => quickGuard.current(token)); else await refreshRolesAndMappings(() => quickGuard.current(token));
        if (!quickGuard.current(token)) return;
        quickGuard.checked(token, true); setQuickError(null);
        notify({ id: crypto.randomUUID(), scope: "system", tone: "info", title: "feedbackCurrentStateChecked" });
      } else { quickGuard.checked(token); setQuickError(new MutationOutcomeUnknown()); }
    } catch (caught) {
      if (!quickGuard.current(token)) return;
      quickGuard.checkFailed(token); setQuickQueryFailed(true); setQuickError(caught as ApiError | Error);
    }
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
    const scope = systemReadScope;
    void readSystemSection("selectedProjects", () => Promise.all(client.project_ids.map(id => getProject(apiFetch, id))), cacheProjects, () => systemReadScopeRef.current === scope);

    setApiKeyScopeDrafts((current) => ({ ...current, [client.id]: client.project_ids }));
    setModalError("");
    setModal({ type: "api-key-manage", client });
  }

  async function submitApiKey(formData: FormData) {
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
    await runModalMutation(() => rotateIntegrationClientKey(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_rotate" }), async (rotated, current) => {
      setApiKeyOneTime({ name: rotated.name, key: rotated.api_key }); await refreshIntegrationClients(current);
    }, "systemApiKeyRotated");
  }

  async function setApiKeyStatus(client: IntegrationClientResponse, active: boolean) {
    await runModalMutation(() => active ? activateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_activate" }) : deactivateIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_deactivate" }), syncIntegrationClient);
  }

  async function revokeApiKey(client: IntegrationClientResponse, accepted: () => void) {
    const updated = await revokeIntegrationClient(apiFetch, client.id, { lock_version: client.lock_version, reason: "manual_revoke" });
    accepted(); syncIntegrationClient(updated);
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
    await runQuickMutation({ kind: "model", id: model.id, field: "is_active", value: true }, () => updateModel(apiFetch, model.id, { is_active: true }), refreshModels);
  }

  async function deactivateModelRow(model: ModelRow, accepted: () => void) {
    const updated = await updateModel(apiFetch, model.id, { is_active: false }); accepted();
    setLiveModels((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
    setModelTableRows((current) => current.map((item) => item.id === model.id ? modelRow(updated) : item));
  }

  function openModelDeleteModal(model: ModelRow) {
    setModelDeleteConfirmation("");
    setModelDeleteDependencies([]);
    setModalError("");
    setModal({ type: "model-delete", model });
  }

  async function submitModelDelete(model: ModelRow) {
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

  function requestPromptLeave(action: () => void) {
    if (promptSaving || promptOperation.checking) return;
    if (promptEditorOpen && promptDraft !== promptBaseline) {
      promptFocusRef.current = document.activeElement as HTMLElement | null;
      setPromptLeave(() => action);
    } else action();
  }

  async function runPromptMutation(write: () => Promise<PromptRow>, intent: NonNullable<typeof promptIntent.current>, title: TranslationKey) {
    const token = promptGuard.begin(); if (token === null) return;
    promptIntent.current = intent; promptReceipt.current = null;
    promptMutationScope.current = promptGuard.scope;
    setPromptSaving(true); setPromptError(""); setPromptMessage("");
    try {
      const prompt = await write();
      if (!promptGuard.current(token)) return;
      promptReceipt.current = prompt; promptGuard.accepted(token);
      // Update the acknowledged baseline now; refreshing the list is a separate read.
      setPromptEditorPrompt(prompt); setPromptBaseline(prompt.content);
      if (intent.kind !== "active") setPromptDraft(prompt.content);
      await refreshPrompts(() => promptGuard.current(token));
      if (!promptGuard.current(token)) return;
      promptGuard.complete(token); setPromptSaving(false); setSelectedPromptId(prompt.id);
      setPromptDraftSourceVersion(null); setPromptEditorOpen(true); setPromptMessage(t(title), "success");
    } catch (caught) {
      if (!promptGuard.current(token)) return;
      promptGuard.failed(token, caught);
      setPromptError(promptGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : errorMessage(caught as ApiError | Error));
    } finally { if (promptGuard.current(token)) setPromptSaving(false); }
  }

  async function queryPromptOutcome() {
    const token = promptGuard.beginCheck(); if (token === null) return;
    try {
      const rows = await listSystemPrompts(apiFetch);
      if (!promptGuard.current(token)) return;
      setSystemPrompts(rows);
      systemReadVersions.current.prompts = (systemReadVersions.current.prompts ?? 0) + 1;
      setReadState("prompts", { scope: systemReadScope, phase: "ready", received: true });
      const sameMutation = promptMutationScope.current === promptGuard.scope;
      const candidateIntent = sameMutation ? promptIntent.current : null;
      const candidateReceipt = sameMutation ? promptReceipt.current : null;
      const targetId = candidateIntent?.kind === "create" ? candidateReceipt?.id : selectedPromptId ?? candidateReceipt?.id ?? candidateIntent?.id;
      const intent = candidateIntent?.kind === "create" || candidateIntent?.id === targetId ? candidateIntent : null;
      const receipt = candidateReceipt?.id === targetId ? candidateReceipt : null;
      const current = rows.find(row => row.id === targetId);
      const confirmed = Boolean(current && (receipt || (intent?.kind === "save" && current.content === intent.content) || (intent?.kind === "active" && current.is_active === intent.active)));
      promptGuard.checked(token, confirmed);
      if (confirmed && current) {
        if (intent?.kind === "create") { setSelectedPromptId(current.id); setPromptEditorOpen(true); }
        if (intent?.kind === "create" || intent?.kind === "save") setPromptDraft(current.content);
        if (intent?.kind === "create" || intent?.kind === "save" || promptDraft === current.content) setPromptLeave(null);
        // Confirm only the current state, not who caused an unacknowledged request.
        setPromptEditorPrompt(current); setPromptBaseline(current.content); setPromptError("");
        setPromptMessage(t("feedbackCurrentStateChecked"));
      } else {
        if (current) { setPromptEditorPrompt(current); setPromptBaseline(current.content); }
        setPromptError(t("feedbackSystemOutcomeChecked"));
        setPromptMessage(t("feedbackCurrentStateChecked"));
      }
    } catch {
      if (!promptGuard.current(token)) return;
      promptGuard.checkFailed(token); setPromptError(t("feedbackOutcomeQueryFailed"));
    }
  }

  async function createGlobalPrompt(modelType: "Chat" | "Judge") {
    await runPromptMutation(() => createSystemPrompt(apiFetch, { prompt_scope: "global", model_type: modelType, content: "", is_active: false }), { kind: "create" }, "systemPromptCreated");
  }

  async function createModelPrompt() {
    const model = liveModels.find(item => item.id === promptModelDraft);
    if (!model || (model.type !== "Chat" && model.type !== "Judge")) return;
    const modelType = model.type;
    await runPromptMutation(() => createSystemPrompt(apiFetch, { prompt_scope: "model", model_type: modelType, model_id: model.id, content: "", is_active: false }), { kind: "create" }, "systemPromptCreated");
  }

  async function savePromptVersion() {
    const selected = systemPrompts.find(prompt => prompt.id === selectedPromptId) ?? promptEditorPrompt;
    if (!selected || promptDraft.length > 8000 || promptDraft === promptBaseline) return;
    if (!promptDraft.trim()) { setPromptError(t("systemPromptBlankContentError")); return; }
    await runPromptMutation(() => addSystemPromptVersion(apiFetch, selected.id, { content: promptDraft, is_active: selected.is_active, change_reason: null }), { kind: "save", id: selected.id, content: promptDraft }, "systemPromptSaved");
  }

  async function togglePromptActive(active: boolean) {
    const selected = systemPrompts.find(prompt => prompt.id === selectedPromptId) ?? promptEditorPrompt;
    if (!selected) return;
    if (active && !selected.content.trim()) { setPromptError(t("systemPromptBlankContentError")); return; }
    await runPromptMutation(() => active ? activateSystemPrompt(apiFetch, selected.id, selected.current_version_id) : deactivateSystemPrompt(apiFetch, selected.id), { kind: "active", id: selected.id, active }, active ? "systemPromptActivated" : "systemPromptDeactivated");
  }

  function selectPrompt(prompt: PromptRow) {
    requestPromptLeave(() => {
      setSelectedPromptId(prompt.id); setPromptDraft(prompt.content); setPromptBaseline(prompt.content);
      setPromptDraftSourceVersion(null);
      setPromptError(selectedPromptId === prompt.id && promptGuard.snapshot().phase === "unknown" ? t("feedbackResultUnknown") : selectedPromptId === prompt.id && promptGuard.snapshot().phase === "read_failed" ? t("feedbackAcceptedReadFailed") : ""); setPromptMessage("");
      setPromptEditorPrompt(prompt); setPromptEditorOpen(true);
    });
  }

  function loadPromptVersionDraft(version: PromptRow["versions"][number]) {
    requestPromptLeave(() => {
      setPromptDraft(version.content); setPromptDraftSourceVersion(version.version_number);
      setPromptMessage(format("systemPromptLoadedVersionDraft", { version: version.version_number }));
    });
  }

  async function submitRole(formData: FormData) {
    const name = modal?.type === "role" && modal.role?.isSystem ? modal.role.name : String(formData.get("name") || "").trim();
    const description = String(formData.get("description") || "").trim() || null;
    await runModalMutation(() => modal?.type === "role" && modal.role ? updateRole(apiFetch, modal.role.id, { lock_version: modal.role.lockVersion, name, description }) : createRole(apiFetch, { name, description }), (_result, current) => refreshRolesAndMappings(current), "systemRoleDataUpdated");
  }

  async function openRoleUsers(role: RoleRow) {
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
    await runModalMutation(() => replaceRoleUsers(apiFetch, modal.role.id, { lock_version: roleUsers.lock_version, user_ids: roleUserDraftIds }), async (response, current) => {
      setRoleUsers(response); setRoleUserDraftIds(response.users.filter(row => row.source === "manual").map(row => row.user_id));
      await refreshRolesAndMappings(current);
    }, "systemManualRoleUsersSaved");
  }

  function openRoleMapping(role: RoleRow) {
    setMappingGroupDraft(role.mappingGroupId ?? "");
    setModalError("");
    setModal({ type: "mapping", role });
  }

  async function saveRoleMapping() {
    if (modal?.type !== "mapping" || modal.role.isActive === false) return;
    await runModalMutation(() => setRoleExternalGroupMapping(apiFetch, modal.role.id, { external_group_id: mappingGroupDraft || null, lock_version: modal.role.lockVersion }), (_result, current) => refreshRolesAndMappings(current), "systemMappingsSaved");
  }

  async function changeRoleLifecycle(role: RoleRow, isActive: boolean, accepted: () => void, current: () => boolean) {
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
    roleMenuTriggerRef.current = trigger.closest("details")?.querySelector("summary") ?? trigger;
    setRoleDeleteConfirmation("");
    setModalError("");
    setModal({ type: "role-delete", role });
  }

  async function submitRoleDelete(role: RoleRow) {
    await runModalMutation(() => deleteRole(apiFetch, role.id, role.lockVersion, roleDeleteConfirmation), (_result, current) => refreshRolesAndMappings(current), "feedbackRoleDeleted");
  }

  function closeModal() {
    if (submitting) return;
    if (modal && dirtyModal === modal) { setDiscardModal(modal); return; }
    const restoreTarget = modal?.type === "role-delete" ? roleMenuTriggerRef.current : null;
    setModal(null);
    if (restoreTarget) window.requestAnimationFrame(() => restoreTarget.focus());
  }

  async function submitUser(formData: FormData) {
    if (modal?.type !== "user") return;
    const payload: Parameters<typeof updateUser>[2] = {
      knowledge_owner: formData.get("knowledge_owner") === "on", system_notes: String(formData.get("system_notes") || "")
    };
    const baseline = modal.user.raw?.manager_delegate_user_id;
    if (baseline !== undefined && formData.has("manager_delegate_user_id")) {
      const selected = String(formData.get("manager_delegate_user_id") || "").trim() || null;
      if (selected !== baseline) payload.manager_delegate_user_id = selected;
    }
    await runModalMutation(() => updateUser(apiFetch, modal.user.id, payload), updated => { setLiveUsers(current => current.map(user => user.id === updated.id ? { ...user, roles: updated.knowledge_owner ? "Knowledge Owner" : "—", status: updated.is_active ? "active" : "inactive", raw: updated } : user)); }, "systemUserLocalFieldsSaved");
  }

  async function toggleUser(user: UserRow, accepted: () => void) {
    const next = user.status !== "active";
    const updated = await updateUserStatus(apiFetch, user.id, next); accepted();
    setLiveUsers((current) => current.map((item) => item.id === user.id ? { ...item, status: updated.is_active ? "active" : "inactive", raw: updated } : item));
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
    await runModalMutation(async () => {
      const configText = String(formData.get("config_advanced") || "{}");
      let config: Record<string, unknown> = {};
      try { config = JSON.parse(configText) as Record<string, unknown>; } catch { throw new UiValidationError("systemConfigJsonInvalid"); }
      if (containsSecretConfigKey(config)) throw new UiValidationError("systemConfigJsonNoSecrets");
      const provider = String(formData.get("provider") || "OpenAI");
      const modelType = String(formData.get("model_type") || "Chat");
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
      const pricingKeys = ["input_cost_per_million_tokens", "output_cost_per_million_tokens", "embedding_cost_per_million_tokens", "ocr_cost_per_page", "ocr_cost_per_image"];
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
  const promptScopeLabel = (prompt: PromptRow) => prompt.prompt_scope === "global" ? t("systemPromptScopeGlobal") : t("systemPromptScopeModel");

  function renderPromptFeedback() {
    const needsQuery = promptOperation.phase === "unknown" || promptOperation.phase === "read_failed";
    const reason = promptError || (promptOperation.phase === "unknown" ? t("feedbackResultUnknown") : promptOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : "");
    return <>
      {reason ? <FeedbackMessage tone={needsQuery ? "warning" : "error"} actions={needsQuery ? <button type="button" className="action-button secondary" disabled={promptOperation.checking} onClick={() => void queryPromptOutcome()}>{t(promptOperation.phase === "read_failed" ? "feedbackReloadResult" : "feedbackQueryOutcome")}</button> : undefined}>{promptOperation.checking ? t("feedbackCheckingOutcome") : localize(reason)}</FeedbackMessage> : null}
      {promptMessage ? <FeedbackMessage tone={promptNotice?.tone ?? "info"}>{localize(promptMessage)}</FeedbackMessage> : null}
    </>;
  }

  function handlePromptDialogKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") { event.stopPropagation(); if (promptLeave) { setPromptLeave(null); promptFocusRef.current?.focus(); } else requestPromptLeave(() => setPromptEditorOpen(false)); }
    if (event.key === "Tab") {
      const controls = Array.from(promptDialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled),textarea:not(:disabled),a[href]") ?? []).filter(item => item.getClientRects().length && !item.closest("[inert]"));
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }

  function renderPromptEditor(prompt: PromptRow) {
    const model = prompt.model_id ? liveModels.find((item) => item.id === prompt.model_id) : null;
    const promptDraftBlank = promptDraft.trim().length === 0;
    const currentPromptBlank = prompt.content.trim().length === 0;
    return (
      <div className="system-prompt-editor system-crud-form">
        {model ? <div className="system-prompt-target"><Bot size={16} /><span>{t("systemPromptTargetModel")}</span><strong>{model.name}</strong><small>{model.provider}</small></div> : null}
        {promptDraftSourceVersion ? <div className="system-prompt-layer-note"><Info size={17} /><div><strong>{format("systemPromptLoadedVersionDraft", { version: promptDraftSourceVersion })}</strong><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div> : null}
        <div className="identity-form-grid">
          <label className="identity-wide-field"><span>{t("systemPromptContent")}</span><textarea readOnly={promptBlocked} maxLength={8000} onChange={(event) => setPromptDraft(event.target.value)} rows={12} value={promptDraft} /><small>{format("systemPromptLength", { count: promptDraft.length, max: 8000 })}{promptDraftBlank ? ` · ${t("systemPromptBlankContentError")}` : ""}</small></label>
        </div>
        <div className="system-prompt-history-heading"><div><h3>{t("systemPromptVersionHistory")}</h3><p>{t("systemPromptVersionAppendOnlyHelp")}</p></div></div>
        <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemVersion")}</th><th>{t("systemLength")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemTime")}</th><th>{t("systemAction")}</th></tr></thead><tbody>{prompt.versions.map((version) => <tr className={promptDraftSourceVersion === version.version_number ? "selected-row" : ""} key={version.id}><td><button className="system-version-load-button" onClick={() => loadPromptVersionDraft(version)} type="button">{format("systemVersionValue", { version: version.version_number })}</button></td><td>{version.content.length}</td><td><StateBadge tone={version.is_active ? "green" : "gray"}>{version.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></td><td>{version.created_at.slice(0, 16).replace("T", " ")}</td><td><button className="icon-text-button" onClick={() => loadPromptVersionDraft(version)} type="button">{t("systemPromptLoadVersionDraft")}</button></td></tr>)}</tbody></table></div>
        <footer><button className="action-button secondary" disabled={!canEditModels || promptSaving || promptBlocked || prompt.is_active || currentPromptBlank} onClick={() => { void togglePromptActive(true); }} type="button"><Check size={16} />{t("systemEnable")}</button><button className="action-button secondary" disabled={!canEditModels || promptSaving || promptBlocked || !prompt.is_active} onClick={() => { void togglePromptActive(false); }} type="button"><X size={16} />{t("systemDisable")}</button><button className="action-button" disabled={!canEditModels || promptSaving || promptBlocked || promptDraftBlank || promptDraft.length > 8000 || promptDraft === promptBaseline} onClick={() => { void savePromptVersion(); }} type="button"><Save size={16} />{t("systemPromptSaveVersion")}</button></footer>
      </div>
    );
  }

  function renderLocalRoleCard(role: RoleRow) {
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

  if (!canViewSystemManagement) {
    return <ForbiddenState />;
  }

  const activeIdentityRun = syncRuns.find((run) => run.status === "queued" || run.status === "running");
  const visibleIdentityMessage = activeIdentityRun
    ? identitySyncProgressText(activeIdentityRun, t, format)
    : identityMessage;

  if (loadedSystemScope !== systemReadScope) return <FeedbackMessage tone="info">{t("loadingData")}</FeedbackMessage>;

  return (
    <section className="system-workspace">
      {systemLoading ? <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("loadingData")}</strong><span>{t("systemLoadingBackend")}</span></div></div> : null}
      {quickError ? <FeedbackMessage tone={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? "warning" : "error"} actions={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? <button type="button" className="action-button secondary" disabled={quickOperation.checking} onClick={() => void queryQuickOutcome()}>{t("feedbackQueryOutcome")}</button> : undefined}><strong>{quickOperation.checking ? t("feedbackCheckingOutcome") : quickOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : quickOperation.phase === "unknown" ? t("feedbackResultUnknown") : errorMessage(quickError)}</strong>{quickQueryFailed ? <p>{t("feedbackOutcomeQueryFailed")}</p> : null}{quickOperation.phase === "unknown" && quickOperation.checked ? <p>{t("feedbackSystemOutcomeChecked")}</p> : null}</FeedbackMessage> : null}
      {systemError ? <FeedbackMessage tone="error"><strong>{errorMessage(systemError)}</strong><button className="text-link" onClick={loadSystem} type="button">{t("retry")}</button></FeedbackMessage> : null}
      <div className="system-overview" aria-label={t("systemOverviewAria")}>
        <div><span className="overview-icon"><UsersRound size={18} /></span><div><small>{t("systemSyncedUsers")}</small><strong>{userOverallTotal === null ? t("systemReadCountUnknown") : formatCount(userOverallTotal, locale)}</strong></div><StateBadge>{t("liveData")}</StateBadge></div>
        <div><span className="overview-icon"><ShieldCheck size={18} /></span><div><small>{t("systemRoleCount")}</small><strong>{roleOverallTotal === null ? t("systemReadCountUnknown") : formatCount(roleOverallTotal, locale)}</strong></div><span className="overview-helper">{format("systemExternalGroupMappings", { count: sectionReady("mappings") ? liveGroupMappings.length : t("systemReadCountUnknown") })}</span></div>
        <div><span className="overview-icon"><Bot size={18} /></span><div><small>{t("systemActiveModels")}</small><strong>{sectionReady("models") ? liveModels.filter((model) => model.status === "active").length : t("systemReadCountUnknown")}</strong></div><span className="overview-helper">{format("systemDefaultModels", { count: sectionReady("models") ? liveModels.filter((model) => model.default).length : t("systemReadCountUnknown") })}</span></div>
        <div><span className="overview-icon"><Activity size={18} /></span><div><small>{t("systemIdentitySync")}</small><strong>{sectionReady("syncRuns") ? syncRuns[0]?.status ?? "—" : t("systemReadCountUnknown")}</strong></div><span className="overview-helper">{sectionReady("syncRuns") ? syncRuns[0]?.started_at?.slice(0, 16).replace("T", " ") ?? t("systemNoLiveDataShort") : t("systemReadUnknown")}</span></div>
      </div>

      <div className="system-tab-shell">
        <div aria-label={t("systemTabsAria")} className="system-tabs" role="tablist">
          {localizedTabs.map((tab, index) => { const Icon = tab.icon; return <button aria-controls={`system-panel-${tab.id}`} aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "active" : ""} id={`system-tab-${tab.id}`} key={tab.id} onClick={() => activateTab(tab.id)} onKeyDown={(event) => handleTabKey(event, index)} ref={(node) => { tabRefs.current[index] = node; }} role="tab" tabIndex={activeTab === tab.id ? 0 : -1} type="button"><Icon size={17} />{tab.label}</button>; })}
        </div>

        <div aria-labelledby={`system-tab-${activeTab}`} className="system-tab-panel" id={`system-panel-${activeTab}`} role="tabpanel">
          {(activeTab === "users" ? ["users", "syncRuns"] : activeTab === "roles" || activeTab === "permissions" ? ["roles", "groups", "mappings"] : activeTab === "models" ? ["models"] : activeTab === "prompts" ? ["prompts", "models"] : activeTab === "apiKeys" ? ["clients", "projects"] : activeTab === "identity" ? ["identity", "providers", "groups", "mappings", "syncRuns", "breakGlass", "status"] : activeTab === "parameters" ? ["parameters"] : ["status"]).map(section => <div key={section}>{renderSectionReadNotice(section)}</div>)}
          {activeTab === "users" ? <>
            <SectionHeader action={<button className="action-button secondary" disabled={!canEditUsers} onClick={runIdentitySync} type="button"><RefreshCw size={16} />{t("systemSyncNow")}</button>} description={t("systemUserManagementDescription")} title={t("systemUserManagementTitle")} />
            <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchUsers")} maxLength={100} onChange={(event) => { setUserQuery(event.target.value); setUserPage(1); }} placeholder={t("systemSearchUsersPlaceholder")} value={userQuery} /></label><select aria-label={t("systemFilterIdentitySource")} onChange={(event) => { setUserSourceFilter(event.target.value); setUserPage(1); }} value={userSourceFilter}><option value="all">{t("systemAllIdentitySources")}</option>{Array.from(new Set(["ldap", "ad", "keycloak", "keycloak_local", "local", ...liveUsers.map(user => user.source)])).map((source) => <option key={source} value={source}>{source}</option>)}</select><span>{format("systemUserCount", { filtered: formatCount(filteredUsers.length, locale), total: formatCount(userTotal, locale) })}</span></div>
            {filteredUsers.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemUser")}</th><th>{t("systemDepartment")}</th><th>{t("systemIdentitySourceColumn")}</th><th>{t("systemRoleColumn")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{filteredUsers.map((user) => <tr key={user.id}><td><strong>{userRowName(user)}</strong><small>{user.email}</small></td><td>{user.department}</td><td>{user.source}</td><td>{user.roles}</td><td><StateBadge tone={user.status === "active" ? "green" : "gray"}>{localizedStatus(user.status)}</StateBadge></td><td><div className="system-row-actions"><button aria-label={format("systemViewUser", { name: userRowName(user) })} className="icon-text-button" onClick={() => setModal({ type: "user", user })} type="button">{t("systemView")} <ChevronRight size={15} /></button><button className="icon-text-button" disabled={!canEditUsers} onClick={() => setModal({ type: "confirm", title: `${user.status === "active" ? t("systemDisable") : t("systemEnable")}${t("systemUser")}`, message: format("systemConfirmToggleUser", { action: user.status === "active" ? t("systemDisable") : t("systemEnable"), name: userRowName(user) }), actionLabel: user.status === "active" ? t("systemDisable") : t("systemEnable"), target: { kind: "user", id: user.id, expected: { field: "is_active", value: user.status !== "active" } }, run: accepted => toggleUser(user, accepted) })} type="button">{user.status === "active" ? t("systemDisable") : t("systemEnable")}</button></div></td></tr>)}</tbody></table></div> : sectionReady("users") ? <EmptyInlineState /> : null}
            {renderListPager("users", userPage, userPageSize, userTotal, () => setUserPage(page => page - 1), userPage * userPageSize < userTotal ? () => setUserPage(page => page + 1) : null, size => { setUserPageSize(size); setUserPage(1); })}
          </> : null}

          {activeTab === "roles" ? <>
            <SectionHeader action={rolesView === "local" ? <button className="action-button" disabled={!canCreateRoles} onClick={() => setModal({ type: "role" })} type="button"><UserRoundCog size={16} />{t("systemAddRole")}</button> : undefined} description={t("systemRolesDescription")} title={t("systemRolesTitle")} />
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
          </> : null}

          {activeTab === "permissions" ? <>
            <SectionHeader action={<div className="system-save-state"><span>{permissionSaved ? <><Check size={15} />{t("systemSaved")}</> : t("systemUnsavedChanges")}</span><button className="action-button" disabled={!canEditPermissions || selectedRoleReadOnly} onClick={savePermissions} title={!canEditPermissions ? t("apiForbidden") : selectedRoleReadOnly ? t("systemRoleReadOnly") : undefined} type="button"><Save size={16} />{t("systemSavePermissions")}</button></div>} description={t("systemPermissionsDescription")} title={t("systemPermissions")} />
            <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchRoles")} maxLength={100} onChange={event => { setRoleQuery(event.target.value); setRolePage(1); }} value={roleQuery} /></label></div>
            {renderListPager("roles", rolePage, rolePageSize, roleTotal, () => setRolePage(page => page - 1), rolePage * rolePageSize < roleTotal ? () => setRolePage(page => page + 1) : null, size => { setRolePageSize(size); setRolePage(1); })}
            <div className="role-selector" aria-label={t("systemSelectRole")}>{filteredLocalRoles.map((role) => <button aria-pressed={selectedRole === role.id} className={`${selectedRole === role.id ? "active" : ""}${role.isActive === false ? " inactive" : ""}`} key={role.id} onClick={() => { setSelectedRole(role.id); setPermissionSaved(true); }} type="button"><span>{role.name}</span><small>{format("systemRoleSelectorSummary", { members: role.members ?? t("systemReadCountUnknown"), groups: role.groups ?? t("systemReadCountUnknown") })} · {role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</small></button>)}</div>
            {selectedRoleReadOnly ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRolePermissionsReadOnlyHelp")}</p></div></FeedbackMessage> : null}
            {liveRoles.length ? <div className="permission-matrix-wrap"><table className="permission-matrix-table"><thead><tr><th>{t("systemMenuPermission")}</th><th>{t("permissionActionView")}</th><th>{t("permissionActionCreate")}</th><th>{t("permissionActionEdit")}</th><th>{t("permissionActionDelete")}</th><th>{t("permissionActionExecute")}</th></tr></thead><tbody>{permissionMenuRows.map((row) => { const state = permissions[selectedRole]?.[row.key] ?? emptyPermissionState()[row.key]; return <tr key={row.key}><td><strong>{t(row.labelKey as TranslationKey)}</strong><small>{t(row.descriptionKey as TranslationKey)}</small></td>{(["view", "create", "edit", "delete", "execute"] as PermissionAction[]).map((action) => { const enabled = permissionActionEnabled(row, action); return <td key={action}><input aria-label={`${liveRoles.find((role) => role.id === selectedRole)?.name ?? t("systemRoleColumn")} ${t(row.labelKey as TranslationKey)} ${t(`permissionAction${action.charAt(0).toUpperCase()}${action.slice(1)}` as TranslationKey)}`} checked={enabled && state[action]} disabled={!canEditPermissions || selectedRoleReadOnly || !enabled || !sectionReady("roles")} onChange={() => togglePermission(row.key, action)} type="checkbox" /></td>; })}</tr>; })}</tbody></table></div> : <EmptyInlineState />}
          </> : null}

          {activeTab === "models" ? <>
            <SectionHeader action={<button className="action-button" disabled={!canCreateModels} onClick={() => openModelModal()} type="button"><Bot size={16} />{t("systemAddModel")}</button>} description={t("systemModelsDescription")} title={t("systemModels")} />
            <div className="model-list-toolbar">
              <label><span>{t("systemModelTypeFilter")}</span><select aria-label={t("systemModelTypeFilter")} onChange={(event) => { setModelTableType(event.target.value); setModelTablePage(1); }} value={modelTableType}><option value="all">{t("systemAllModelTypes")}</option><option value="Chat">{t("labelChat")}</option><option value="Embedding">Embedding</option><option value="OCR">OCR</option><option value="Judge">Judge</option></select></label>
              <span aria-live="polite">{format("systemModelResultRange", { first: modelTableFirst, last: modelTableLast, total: modelTableTotal })}</span>
            </div>
            {modelTableError ? <FeedbackMessage tone="error"><strong>{localize(modelTableError)}</strong><button className="icon-text-button" onClick={() => { void refreshModelTable(); }} type="button"><RefreshCw size={14} />{t("retry")}</button></FeedbackMessage> : null}
            {modelTableLoading ? <div className="system-table-loading" role="status"><LoaderCircle className="spin" size={20} /><span>{t("systemLoadingModels")}</span></div> : null}
            {!modelTableLoading && modelTableRows.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemName")}</th><th>{t("systemModelType")}</th><th>{t("labelProvider")}</th><th>{t("systemModel")}</th><th>{t("systemSecret")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{modelTableRows.map((model) => {
              const modelIsActive = model.status === "active";
              return <tr key={model.id}><td><strong>{model.name}</strong>{model.default ? <small>{format("systemDefaultModelLabel", { type: model.type })}</small> : null}</td><td>{model.type}</td><td>{model.provider}</td><td>{aiModelProviderName(model.raw?.config)}</td><td><span className="secret-state"><LockKeyhole size={14} />{model.raw?.api_key_configured || model.raw?.api_key_secret_ref ? t("systemConfigured") : t("systemNotConfigured")}</span></td><td><div className="model-status-stack"><StateBadge tone={modelIsActive ? "green" : "gold"}>{localizedStatus(model.status)}</StateBadge>{model.raw?.last_test_status ? <><StateBadge tone={model.raw.last_test_status === "success" ? "green" : model.raw.last_test_status === "failed" ? "coral" : "gold"}>{localizedOperationStatus(model.raw.last_test_status)}</StateBadge><small>{model.raw.last_tested_at ? new Date(model.raw.last_tested_at).toLocaleString() : null}{model.raw.last_test_latency_ms !== null ? ` · ${model.raw.last_test_latency_ms} ms` : ""}</small></> : <small>{t("systemConnectionNotTested")}</small>}</div></td><td><div className="system-row-actions"><button className="icon-text-button" disabled={!canEditModels} onClick={() => openModelModal(model)} type="button">{t("systemEdit")}</button><button className="icon-text-button" disabled={!canEditModels || quickBlocked || model.default || !modelIsActive} onClick={() => { void runQuickMutation({ kind: "model", id: model.id, field: "is_default", value: true }, () => setDefaultModel(apiFetch, model.id), refreshModels); }} type="button">{t("systemSetDefault")}</button><button className="icon-text-button" disabled={!canEditModels} onClick={() => { void runModelConnectionTest(model); }} type="button">{t("systemTest")}</button>{modelIsActive ? <button className="icon-text-button" disabled={!canEditModels} onClick={() => setModal({ type: "confirm", title: t("systemDisableModel"), message: t("systemDisableModelHelp"), actionLabel: t("systemDisable"), successTitle: "systemModelDeactivated", target: { kind: "model", id: model.id, expected: { field: "is_active", value: false } }, run: accepted => deactivateModelRow(model, accepted) })} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={!canEditModels || quickBlocked} onClick={() => { void activateModel(model); }} type="button">{t("systemEnable")}</button>}<button aria-label={format("systemDeleteModelAria", { name: model.name })} className="icon-text-button destructive" disabled={!canDeleteModels} onClick={() => openModelDeleteModal(model)} type="button"><Trash2 size={14} />{t("systemDelete")}</button></div></td></tr>;
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
            {!promptEditorOpen ? renderPromptFeedback() : null}

            <div className="system-prompt-layer-stack"><Layers3 size={17} /><div><strong>{t("systemPromptLayerOrderTitle")}</strong><span>{t("systemPromptLayerOrderHelp")}</span></div></div>
            <section className="system-prompt-area">
              <div className="system-subsection-title"><div><h3><Globe2 size={18} />{t("systemPromptGlobalSection")}</h3><p>{t("systemPromptGlobalSectionHelp")}</p></div></div>
              <div className="system-prompt-global-grid">
                {globalChatPrompt ? <button className={selectedPromptId === globalChatPrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalChatPrompt)} type="button"><span><MessageSquareText size={18} />{t("systemPromptGlobalChatTitle")}</span><strong>{format("systemVersionValue", { version: globalChatPrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalChatPrompt.is_active ? "green" : "gray"}>{globalChatPrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving || promptBlocked || !sectionReady("prompts")} onClick={() => { void createGlobalPrompt("Chat"); }} type="button"><strong>{t("systemPromptGlobalChatTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
                {globalJudgePrompt ? <button className={selectedPromptId === globalJudgePrompt.id ? "system-prompt-summary active" : "system-prompt-summary"} onClick={() => selectPrompt(globalJudgePrompt)} type="button"><span><ShieldCheck size={18} />{t("systemPromptGlobalJudgeTitle")}</span><strong>{format("systemVersionValue", { version: globalJudgePrompt.current_version_number ?? "—" })}</strong><StateBadge tone={globalJudgePrompt.is_active ? "green" : "gray"}>{globalJudgePrompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></button> : <button className="system-prompt-empty-global" disabled={!canCreateModels || promptSaving || promptBlocked || !sectionReady("prompts")} onClick={() => { void createGlobalPrompt("Judge"); }} type="button"><strong>{t("systemPromptGlobalJudgeTitle")}</strong><p>{t("systemPromptGlobalMissing")}</p></button>}
              </div>
            </section>
            <section className="system-prompt-area">
              <div className="system-subsection-title"><div><h3><Bot size={18} />{t("systemPromptModelSection")}</h3><p>{t("systemPromptModelSectionHelp")}</p></div><div className="system-toolbar compact"><select aria-label={t("systemPromptSelectModel")} onChange={(event) => setPromptModelDraft(event.target.value)} value={promptModelDraft}>{promptModelOptions.length ? promptModelOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.type}</option>) : <option value="">{t("systemPromptNoModelsAvailable")}</option>}</select><button className="action-button secondary" disabled={!canCreateModels || !promptModelDraft || promptSaving || !sectionReady("prompts") || !sectionReady("models")} onClick={() => { void createModelPrompt(); }} type="button"><Plus size={16} />{t("systemPromptAddModel")}</button></div></div>
              {modelSpecificPrompts.length ? <div className="system-table-wrap system-prompt-model-table"><table className="system-table"><thead><tr><th>{t("systemModel")}</th><th>{t("systemModelType")}</th><th>{t("systemVersion")}</th><th>{t("systemStatusColumn")}</th></tr></thead><tbody>{modelSpecificPrompts.map((prompt) => <tr className={selectedPromptId === prompt.id ? "selected-row" : ""} key={prompt.id} onClick={() => selectPrompt(prompt)}><td><button className="text-link system-prompt-open" type="button" onClick={(event) => { event.stopPropagation(); selectPrompt(prompt); }} aria-label={format("systemPromptOpenForModel", { name: liveModels.find(model => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—" })}><MessageSquareText size={16} aria-hidden="true" /><strong>{liveModels.find((model) => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—"}</strong></button><small>{prompt.content_hash ?? t("systemPromptBlankHash")}</small></td><td>{prompt.model_type}</td><td>{prompt.current_version_number ?? "—"}</td><td><StateBadge tone={prompt.is_active ? "green" : "gray"}>{prompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></td></tr>)}</tbody></table></div> : sectionReady("prompts") ? <EmptyInlineState>{t("systemPromptNoModelPrompts")}</EmptyInlineState> : null}
            </section>
          </> : null}

          {activeTab === "apiKeys" ? <>
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
                  {identityErrors.issuer ? <FeedbackField id="identity-issuer-error">{identityErrorMessage("issuer")}</FeedbackField> : null}
                </label>
                <label className={`identity-field ${identityErrors.realm ? "has-error" : ""}`} htmlFor="identity-realm">
                  <span>{t("labelRealm")}</span>
                  <input aria-describedby={identityErrors.realm ? "identity-realm-error" : undefined} aria-invalid={Boolean(identityErrors.realm)} id="identity-realm" onChange={(event) => updateIdentity("realm", event.target.value)} value={identitySettings.realm} />
                  {identityErrors.realm ? <FeedbackField id="identity-realm-error">{identityErrorMessage("realm")}</FeedbackField> : null}
                </label>
                <label className={`identity-field ${identityErrors.clientId ? "has-error" : ""}`} htmlFor="identity-client-id">
                  <span>{t("labelClientId")}</span>
                  <input aria-describedby={identityErrors.clientId ? "identity-client-id-error" : undefined} aria-invalid={Boolean(identityErrors.clientId)} id="identity-client-id" onChange={(event) => updateIdentity("clientId", event.target.value)} value={identitySettings.clientId} />
                  {identityErrors.clientId ? <FeedbackField id="identity-client-id-error">{identityErrorMessage("clientId")}</FeedbackField> : null}
                </label>
                <label className={`identity-field ${identityErrors.audience ? "has-error" : ""}`} htmlFor="identity-audience">
                  <span>{t("labelAudience")}</span>
                  <input aria-describedby={identityErrors.audience ? "identity-audience-error" : undefined} aria-invalid={Boolean(identityErrors.audience)} id="identity-audience" onChange={(event) => updateIdentity("audience", event.target.value)} value={identitySettings.audience} />
                  {identityErrors.audience ? <FeedbackField id="identity-audience-error">{identityErrorMessage("audience")}</FeedbackField> : null}
                </label>
                <label className={`identity-field identity-wide-field ${identityErrors.discoveryUrl ? "has-error" : ""}`} htmlFor="identity-discovery-url">
                  <span>{t("labelDiscoveryJwksUrl")}</span>
                  <input aria-describedby={identityErrors.discoveryUrl ? "identity-discovery-url-error" : undefined} aria-invalid={Boolean(identityErrors.discoveryUrl)} id="identity-discovery-url" onChange={(event) => updateIdentity("discoveryUrl", event.target.value)} value={identitySettings.discoveryUrl} />
                  {identityErrors.discoveryUrl ? <FeedbackField id="identity-discovery-url-error">{identityErrorMessage("discoveryUrl")}</FeedbackField> : null}
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
                  {identityErrors.schedule ? <FeedbackField id="identity-sync-schedule-error">{identityErrorMessage("schedule")}</FeedbackField> : null}
                </label>
                <label className={`identity-field ${identityErrors.timezone ? "has-error" : ""}`} htmlFor="identity-timezone">
                  <span>{t("systemIdentityTimezone")}</span>
                  <input aria-describedby={identityErrors.timezone ? "identity-timezone-error" : undefined} aria-invalid={Boolean(identityErrors.timezone)} disabled={!identityUnlocked || !canEditSystemManagement} id="identity-timezone" onChange={(event) => updateIdentity("timezone", event.target.value)} value={identitySettings.timezone} />
                  {identityErrors.timezone ? <FeedbackField id="identity-timezone-error">{identityErrorMessage("timezone")}</FeedbackField> : null}
                </label>
                <button className="action-button secondary identity-sync-action" disabled={!canEditSystemManagement || identitySyncing || Boolean(activeIdentityRun) || !identityWorkerAvailable} onClick={runIdentitySync} type="button">{identitySyncing || activeIdentityRun ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{identitySyncing || activeIdentityRun ? t("identitySyncInProgress") : t("identitySyncNow")}</button>
              </div>
              <div className="identity-directory-heading"><div><strong>{t("identityDirectoryProviders")}</strong><small>{t("identityDirectoryProvidersHelp")}</small></div></div>
              {directoryProviderError ? <FeedbackMessage tone="error">{t("identityDirectoryProviderUnavailable")}</FeedbackMessage> : null}
              <div className="directory-settings-grid">
                {directoryProviders.map((provider) => <article className="directory-setting-card" key={provider.id}><header><div><h3>{provider.name}</h3><p>{provider.vendor} · {provider.id}</p></div><StateBadge tone={provider.enabled ? "green" : "gray"}>{provider.enabled ? t("systemEnabled") : t("systemDisabled")}</StateBadge></header><label><span>{t("identityDirectoryFilter")}</span><textarea disabled={!identityUnlocked || !canEditSystemManagement} onChange={(event) => setDirectoryFilterDrafts((current) => ({ ...current, [provider.id]: event.target.value }))} placeholder={t("identityDirectoryFilterPlaceholder")} rows={3} value={directoryFilterDrafts[provider.id] ?? ""} /><small>{t("identityDirectoryFilterHelp")}</small></label><footer><small>{format("identityProviderCheckedAt", { time: provider.checked_at.slice(0, 16).replace("T", " ") })}</small><button className="action-button secondary" disabled={!identityUnlocked || !canEditSystemManagement || savingDirectoryProviderId !== null} onClick={() => { void saveDirectoryFilter(provider); }} type="button">{savingDirectoryProviderId === provider.id ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}{t("identitySaveFilter")}</button></footer></article>)}
              </div>
              {sectionReady("providers") && !directoryProviderError && !directoryProviders.length ? <EmptyInlineState>{t("identityDirectoryProviderEmpty")}</EmptyInlineState> : null}
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
                {identityReauthError ? <FeedbackMessage tone="error"><span>{localize(identityReauthError)}</span></FeedbackMessage> : null}
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
            </> : sectionReady("status") ? <EmptyInlineState>{t("systemStatusUnavailable")}</EmptyInlineState> : null}
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemSecurityMasking")}</strong><p>{t("systemSecurityMaskingHelp")}</p></div></div>
          </> : null}

          {activeTab === "parameters" ? <>
            <SectionHeader action={<div className="system-save-state"><button className="action-button secondary" disabled={!canEditParameters || !sectionReady("parameters") || !ocrDefaults} onClick={restoreParameters} type="button"><RotateCcw size={16} />{t("systemRestoreDefaults")}</button><button className="action-button" disabled={!canEditParameters || !sectionReady("parameters") || !ocrSettingsHash} onClick={saveParameters} title={!canEditParameters ? t("apiForbidden") : undefined} type="button"><Save size={16} />{t("systemSaveParameters")}</button></div>} description={t("systemParametersDescription")} title={t("systemParameters")} />
            <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("liveData")}</strong><span>{t("systemParametersLiveHelp")}</span></div></div>
            <div className="parameter-grid" data-session-draft-key="system.parameters">
              <label className={parameterErrors.uploadLimitMb ? "has-error" : ""}><span>{t("systemUploadLimitLabel")} <em>MB</em></span><input aria-describedby="upload-limit-help" data-session-draft-field="uploadLimitMb" max={1024} min={1} onChange={(event) => updateParameter("uploadLimitMb", Number(event.target.value))} type="number" value={parameters.uploadLimitMb} /><small id="upload-limit-help">{t("systemUploadLimitHelp")}</small>{parameterErrors.uploadLimitMb ? <strong>{parameterErrors.uploadLimitMb}</strong> : null}</label>
              <label className={parameterErrors.timezone ? "has-error" : ""}><span>{t("systemDefaultTimezoneLabel")} <em>{t("systemIdentityTimezone")}</em></span><input aria-describedby="timezone-help" data-session-draft-field="timezone" onChange={(event) => updateParameter("timezone", event.target.value)} value={parameters.timezone} /><small id="timezone-help">{t("systemDefaultTimezoneHelp")}</small>{parameterErrors.timezone ? <strong>{parameterErrors.timezone}</strong> : null}</label>
              <label className={parameterErrors.stagingTtlDays ? "has-error" : ""}><span>{t("systemStagingTtlLabel")} <em>{t("systemDaysUnit")}</em></span><input aria-describedby="ttl-help" data-session-draft-field="stagingTtlDays" max={90} min={1} onChange={(event) => updateParameter("stagingTtlDays", Number(event.target.value))} type="number" value={parameters.stagingTtlDays} /><small id="ttl-help">{t("systemStagingTtlHelp")}</small>{parameterErrors.stagingTtlDays ? <strong>{parameterErrors.stagingTtlDays}</strong> : null}</label>
              <label className={parameterErrors.sessionDraftTtlMinutes ? "has-error" : ""}><span>{t("systemSessionDraftTtlLabel")} <em>{t("systemMinutesUnit")}</em></span><input aria-describedby="draft-ttl-help" data-session-draft-field="sessionDraftTtlMinutes" max={120} min={0} onChange={(event) => updateParameter("sessionDraftTtlMinutes", Number(event.target.value))} type="number" value={parameters.sessionDraftTtlMinutes} /><small id="draft-ttl-help">{t("systemSessionDraftTtlHelp")}</small>{parameterErrors.sessionDraftTtlMinutes ? <strong>{parameterErrors.sessionDraftTtlMinutes}</strong> : null}</label>
              <label className={parameterErrors.ocrPageOutputTokens ? "has-error" : ""}><span>{t("ocrPageTokenSettingLabel")} <em>{t("ocrTokenUnit")}</em></span><input disabled={!canEditParameters || !sectionReady("parameters")} aria-describedby="ocr-page-help" data-session-draft-field="ocrPageOutputTokens" min={1} max={2147483647} type="number" value={parameters.ocrPageOutputTokens ?? ""} onChange={(event) => updateParameter("ocrPageOutputTokens", Number(event.target.value))} /><small id="ocr-page-help">{t("ocrPageTokenSettingHelp")} {parameters.ocrPageOutputTokens != null ? format("ocrTokenReadableValue", { value: formatCount(parameters.ocrPageOutputTokens, locale) }) : null}</small>{parameterErrors.ocrPageOutputTokens ? <strong>{t("ocrTokenPositiveInteger")}</strong> : null}</label>
              <label className={parameterErrors.ocrDocumentOutputTokens ? "has-error" : ""}><span>{t("ocrDocumentTokenSettingLabel")} <em>{t("ocrTokenUnit")}</em></span><input disabled={!canEditParameters || !sectionReady("parameters")} aria-describedby="ocr-document-help" data-session-draft-field="ocrDocumentOutputTokens" min={1} max={2147483647} type="number" value={parameters.ocrDocumentOutputTokens ?? ""} onChange={(event) => updateParameter("ocrDocumentOutputTokens", Number(event.target.value))} /><small id="ocr-document-help">{t("ocrDocumentTokenSettingHelp")} {parameters.ocrDocumentOutputTokens != null ? format("ocrTokenReadableValue", { value: formatCount(parameters.ocrDocumentOutputTokens, locale) }) : null}</small>{parameterErrors.ocrDocumentOutputTokens ? <strong>{t(parameterErrors.ocrDocumentOutputTokens === "ocrTokenDocumentTooSmall" ? "ocrTokenDocumentTooSmall" : "ocrTokenPositiveInteger")}</strong> : null}</label>
            </div>
            <div aria-live="polite" className="parameter-footer"><div><Clock3 size={16} /><span>{t("systemParametersLiveValues")}</span></div>{parameterMessage ? <FeedbackMessage tone={parameterNotice?.tone ?? "error"}>{localize(parameterMessage)}</FeedbackMessage> : null}<small>{format("systemParametersSavedSummary", { uploadLimitMb: savedParameters.uploadLimitMb, timezone: savedParameters.timezone, stagingTtlDays: savedParameters.stagingTtlDays, sessionDraftTtlMinutes: savedParameters.sessionDraftTtlMinutes })}</small></div>
            <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemDeploymentSettingsExcluded")}</strong><p>{t("systemDeploymentSettingsExcludedHelp")}</p></div></div>
          </> : null}
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
      {apiKeyOneTime && !modal ? <div className="system-modal-backdrop" onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); setApiKeyOneTime(null); }
        if (event.key === "Tab") {
          const dialog = apiKeyDialogRef.current;
          const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]') ?? []).filter(control => control.getClientRects().length);
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
          else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
        }
      }} onMouseDown={(event) => { if (event.target === event.currentTarget) setApiKeyOneTime(null); }} role="presentation">
        <section ref={apiKeyDialogRef} aria-labelledby="system-api-key-onetime-title" aria-modal="true" className="system-reauth-modal system-api-key-onetime-modal" role="dialog">
          <header><span><KeyRound size={20} /></span><div><small>{t("systemApiKeys")}</small><h2 id="system-api-key-onetime-title">{format("systemApiKeyOneTimeTitle", { name: apiKeyOneTime.name })}</h2></div><button aria-label={t("close")} className="modal-close-button" onClick={() => setApiKeyOneTime(null)} type="button"><X size={18} /></button></header>
          <div className="system-api-key-once" role="status"><KeyRound size={18} /><div><code>{apiKeyOneTime.key}</code><small>{t("systemApiKeyOneTimeHelp")}</small></div></div>
          <footer><button className="action-button secondary" onClick={() => { void navigator.clipboard.writeText(apiKeyOneTime.key); }} type="button">{t("systemApiKeyCopy")}</button><button className="action-button" onClick={() => setApiKeyOneTime(null)} type="button">{t("close")}</button></footer>
        </section>
      </div> : null}
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
          {modal.type === "user" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitUser(new FormData(event.currentTarget)); }}>
            <div className="system-detail-grid"><div><small>{t("systemName")}</small><strong>{userRowName(modal.user)}</strong></div><div><small>{t("labelEmail")}</small><strong>{modal.user.email}</strong></div><div><small>{t("systemSourceColumn")}</small><strong>{modal.user.source}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.user.status)}</strong></div></div>
            <label className="identity-toggle"><input defaultChecked={Boolean(modal.user.raw?.knowledge_owner)} name="knowledge_owner" type="checkbox" /><span>{t("labelKnowledgeOwner")}</span></label>
            <label><span>{t("systemManagerDelegateOptional")}</span><input defaultValue={modal.user.raw?.manager_delegate_user_id ?? ""} disabled={modal.user.raw?.manager_delegate_user_id === undefined} name="manager_delegate_user_id" placeholder="UUID" />{modal.user.raw?.manager_delegate_user_id === undefined ? <small>{t("systemManagerDelegateUnavailable")}</small> : null}</label>
            <label><span>{t("labelSystemNotes")}</span><textarea defaultValue={modal.user.raw?.system_notes ?? ""} name="system_notes" rows={4} /></label>
            <footer><button className="action-button secondary" onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={!canEditUsers || submitting} type="submit"><Save size={16} />{t("save")}</button></footer>
          </FeedbackForm> : null}
          {modal.type === "role" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitRole(new FormData(event.currentTarget)); }}>
            <label><span>{t("systemRoleName")}</span><input defaultValue={modal.role?.name ?? ""} disabled={modal.role?.isSystem || modal.role?.isActive === false} name="name" required /></label>
            <label><span>{t("systemDescription")}</span><textarea defaultValue={modal.role?.description ?? ""} disabled={modal.role?.isActive === false} name="description" rows={3} /></label>
            {modal.role?.isSystem ? <div className="system-security-note"><LockKeyhole size={17} /><div><strong>{t("systemRoleProtection")}</strong><p>{t("systemRoleProtectionHelp")}</p></div></div> : null}
            {modal.role?.isActive === false ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleReadOnlyHelp")}</p></div></FeedbackMessage> : null}
            <footer><button className="action-button secondary" onClick={closeModal} type="button">{modal.role?.isActive === false ? t("close") : t("cancel")}</button>{modal.role?.isActive === false ? null : <button className="action-button" disabled={submitting || (!modal.role && !canCreateRoles) || (Boolean(modal.role) && !canEditRoles)} type="submit"><Save size={16} />{t("save")}</button>}</footer>
          </FeedbackForm> : null}
          {modal.type === "role-users" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form role-user-editor" onSubmit={(event) => { event.preventDefault(); void saveRoleUsers(); }}>
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
          </FeedbackForm> : null}
          {modal.type === "mapping" ? <div className="system-crud-form">
            <p className="system-modal-help">{format("systemRoleMappingHelp", { role: modal.role.name })}</p>
            {modal.role.isActive === false ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRoleMappingReadOnlyHelp")}</p></div></FeedbackMessage> : null}
            <div className="system-mapping-editor"><label><span>{t("systemLdapGroup")}<small>{t("systemOneToOneMappingHelp")}</small></span><select autoFocus disabled={modal.role.isActive === false || !canEditRoles} onChange={(event) => setMappingGroupDraft(event.target.value)} value={mappingGroupDraft}><option value="">{t("systemNoMapping")}</option>{availableMappingGroups.map((group) => <option key={group.id} value={group.id}>{group.path || group.group_name} · {format("systemMemberCount", { count: group.member_count })}</option>)}</select></label></div>
            <div className="system-security-note"><Info size={17} /><div><strong>{t("systemMappingImmediateTitle")}</strong><p>{t("systemMappingImmediateHelp")}</p></div></div>
            <footer><button className="action-button secondary" onClick={closeModal} type="button">{modal.role.isActive === false || !canEditRoles ? t("close") : t("cancel")}</button>{modal.role.isActive === false || !canEditRoles ? null : <button className="action-button" disabled={submitting} onClick={saveRoleMapping} type="button"><Save size={16} />{t("systemSaveMappings")}</button>}</footer>
          </div> : null}
          {modal.type === "role-delete" ? <div className="system-crud-form role-delete-content">
            <FeedbackMessage tone="warning"><div><strong>{t("systemDeleteRoleWarningTitle")}</strong><p>{t("systemDeleteRoleWarningHelp")}</p></div></FeedbackMessage>
            <div className="system-detail-grid"><div><small>{t("systemRoleColumn")}</small><strong>{modal.role.name}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{modal.role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</strong></div><div><small>{t("systemMappedLdapGroup")}</small><strong>{externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.path || externalGroups.find((group) => group.id === modal.role.mappingGroupId)?.group_name || t("systemNoMapping")}</strong></div><div><small>{t("systemMembersColumn")}</small><strong>{modal.role.members ?? t("systemReadCountUnknown")}</strong></div></div>
            <ul className="role-delete-impact"><li>{t("systemDeleteRoleImpactHidden")}</li><li>{t("systemDeleteRoleImpactMapping")}</li><li>{t("systemDeleteRoleImpactHistory")}</li></ul>
            <label><span>{format("systemDeleteRoleConfirmationLabel", { name: modal.role.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setRoleDeleteConfirmation(event.target.value)} placeholder={modal.role.name} value={roleDeleteConfirmation} /><small>{t("systemDeleteRoleConfirmationHelp")}</small></label>
            <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked || roleDeleteConfirmation !== modal.role.name} onClick={() => { void submitRoleDelete(modal.role); }} type="button"><Trash2 size={16} />{t("systemDeleteRolePermanently")}</button></footer>
          </div> : null}
          {modal.type === "model" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form" onSubmit={(event) => { event.preventDefault(); void submitModel(new FormData(event.currentTarget)); }}>
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
            <label><span>{t("systemAdvancedConfigJson")}</span><textarea defaultValue={JSON.stringify(modal.model?.raw?.config ?? {}, null, 2)} name="config_advanced" rows={5} /><small>{t("systemAdvancedConfigHelp")}</small>{modelTypeDraft === "Embedding" ? <small>{t("systemEmbeddingCapacityHelp")}</small> : null}</label>
            <label className="identity-toggle"><input defaultChecked={modal.model?.status !== "inactive"} name="is_active" type="checkbox" /><span>{t("systemEnable")}</span></label>
            <label className="identity-toggle"><input defaultChecked={modal.model?.default ?? false} name="is_default" type="checkbox" /><span>{t("systemSetTypeDefault")}</span></label>
            <footer><button className="action-button secondary" onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button" disabled={submitting || (!modal.model && !canCreateModels) || (Boolean(modal.model) && !canEditModels) || (modelCredentialClearDraft && modelCredentialClearConfirmation !== modal.model?.name)} type="submit">{modal.model ? <Save size={16} /> : <Plus size={16} />}{modal.model ? t("systemSaveModel") : t("systemAddModel")}</button></footer>
          </FeedbackForm> : null}
          {modal.type === "model-delete" ? <div className="system-crud-form model-delete-content">
            <FeedbackMessage tone="warning"><div><strong>{t("systemDeleteModelWarningTitle")}</strong><p>{t("systemDeleteModelWarningHelp")}</p></div></FeedbackMessage>
            <div className="system-detail-grid"><div><small>{t("systemModel")}</small><strong>{modal.model.name}</strong></div><div><small>{t("systemModelType")}</small><strong>{modal.model.type}</strong></div><div><small>{t("labelProvider")}</small><strong>{modal.model.provider}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.model.status)}</strong></div></div>
            {modelDeleteDependencies.length ? <section className="model-delete-dependencies"><strong>{t("systemDeleteModelBlockedTitle")}</strong><p>{t("systemDeleteModelBlockedHelp")}</p><ul>{modelDeleteDependencies.map((dependency) => <li key={dependency.type}><span>{modelDeleteDependencyLabel(dependency.type)}</span><strong>{dependency.count}</strong></li>)}</ul></section> : null}
            <label><span>{format("systemDeleteModelConfirmationLabel", { name: modal.model.name })}</span><input autoComplete="off" autoFocus onChange={(event) => setModelDeleteConfirmation(event.target.value)} placeholder={modal.model.name} value={modelDeleteConfirmation} /><small>{t("systemDeleteModelConfirmationHelp")}</small></label>
            <footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked || modelDeleteConfirmation !== modal.model.name} onClick={() => { void submitModelDelete(modal.model); }} type="button"><Trash2 size={16} />{t("systemDeleteModelPermanently")}</button></footer>
          </div> : null}
          {modal.type === "api-key-create" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void submitApiKey(new FormData(event.currentTarget)); }}>
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
          </FeedbackForm> : null}
          {modal.type === "api-key-manage" ? <FeedbackForm inert={discardModal === modal} outcomeUnknown={modalBlocked} className="system-crud-form system-api-key-modal-form" onSubmit={(event) => { event.preventDefault(); void saveApiKeyManagement(modal.client, new FormData(event.currentTarget)); }}>
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
          </FeedbackForm> : null}
          {modal.type === "confirm" ? <div className="system-crud-form"><p>{localize(modal.message)}</p><footer><button className="action-button secondary" disabled={submitting} onClick={closeModal} type="button">{t("cancel")}</button><button className="action-button danger" disabled={submitting || modalBlocked} onClick={() => { void runModalMutation(modal.run, () => {}, modal.successTitle); }} type="button">{localize(modal.actionLabel)}</button></footer></div> : null}
        </section>
      </div> : null}
    </section>
  );
}
