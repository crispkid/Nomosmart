"use client";

import { DropdownSelect } from "@/components/DropdownSelect";
import ProtocolIdentityPanel from "./ProtocolIdentityPanel";
import SystemParameterSettings from "./SystemParameterSettings";
import { SettingsCard } from "./SettingsCard";
import { useModalFocus } from "./useModalFocus";
import { apiBaseUrl } from "@/lib/oidc";
import { identitySourceLabel } from "@/lib/identitySource";

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
import { Activity, Bot, Check, ChevronDown, ChevronLeft, ChevronRight, Clock3, DatabaseZap, Ellipsis, Eye, Globe2, Info, KeyRound, Link2, LoaderCircle, LockKeyhole, MessageSquareText, Layers3, Plus, Pencil, RefreshCw, RotateCcw, Save, Search, Settings2, ShieldCheck, SlidersHorizontal, Trash2, Unlink, UserRoundCog, UsersRound, X } from "lucide-react";
import { getIdentitySyncRun, getBreakGlassStatus, getPermissions, getRoleUsers, getSystemStatus, activateIntegrationClient, createIntegrationClient, listSystemPrompts, listExternalGroupMappings, listExternalGroups, listModels, listModelsPage, listRoles, listUsersPage, listRolesPage, listProjectsPage, listIntegrationClientsPage, getUser, getRole, getIntegrationClient, getProject, deactivateIntegrationClient, replaceIntegrationClientProjectScopes, replacePermissions, replaceRoleUsers, revokeIntegrationClient, rotateIntegrationClientKey, updateIntegrationClient, addSystemPromptVersion, activateSystemPrompt, createSystemPrompt, deactivateSystemPrompt, type AIModelResponse, type AIModelPayload, type ApiError, type BreakGlassStatusResponse, type ExternalGroupResponse, type IdentitySyncRunResponse, type IntegrationClientResponse, type OperationComponentStatus, type OperationsStatusResponse, type PermissionMatrixResponse, type ProjectResponse, type RoleResponse, type RoleUsersResponse, type SystemPromptResponse, type UserSummary, createModel, createRole, deleteRole, deleteModel, listIdentitySyncRuns, queueIdentitySync, setDefaultModel, setRoleExternalGroupMapping, testModel, updateModel, updateRole, updateUser, updateUserStatus } from "@/lib/api";
import { AIModelCredentialClearControl, OpenAiApiModeField } from "@/components/AIModelCompatibilityFields";
import { aiModelProviderName } from "@/components/AIModelInventoryFields";
import { ForbiddenState } from "@/components/AppShell";
import { useAuth } from "@/components/AuthProvider";
import { userRow, roleRow, roleMemberCounts, type UserRow, type RoleRow } from "@/lib/systemManagement";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import { formatPersonName } from "@/lib/personName";
import { settingsSections, settingsPositionUrl, legacySettingsPositions, type SettingsPosition, type SystemTabId } from "@/lib/systemRouteState";

const settingsPanelLabels: Record<string, TranslationKey> = {
  users: "systemUsers", roles: "systemRoles", permissions: "systemPermissions", login: "protocolSignInMethod", directory: "protocolDirectoryTitle", credentials: "protocolCredentials", sync: "protocolScheduleTitle", "sync-history": "protocolSyncHistory", emergency: "identityEmergencyAccess", models: "systemModels", prompts: "systemPrompts", upload: "settingsUpload", retention: "settingsRetention", ocr: "settingsOCR", clients: "settingsApiKeys", time: "settingsTime", drafts: "settingsDrafts", runtime: "settingsRuntime", dependencies: "systemDependencies", providers: "systemAiProviders", errors: "systemRecentErrors"
};
const settingsPanelHelp: Record<string, TranslationKey> = {
  users: "systemUserManagementDescription", roles: "systemRolesDescription", permissions: "systemPermissionsDescription", login: "protocolSettingsHelp", directory: "protocolDirectoryHelp", credentials: "protocolCredentialsHelp", sync: "protocolDailyDelayHelp", models: "systemModelsDescription", prompts: "systemPromptsDescription", upload: "settingsUploadHelp", retention: "settingsRetentionHelp", ocr: "ocrRequestTokenSettingHelp", clients: "systemApiKeysDescription", time: "settingsTimezoneHelp", drafts: "systemSessionDraftTtlHelp", runtime: "systemStatusDescription"
};

const settingsSearchFields: Record<string, TranslationKey[]> = {
  models: ["labelProvider", "labelModelName", "labelEndpoint", "systemChatEmbeddingPairs", "systemModelPricingTitle"],
  prompts: ["systemPromptGlobalMissing", "systemVersion"],
  login: ["labelIssuer", "protocolClientId", "protocolScopes", "protocolMappingClaim"],
  directory: ["protocolUsersDN", "protocolGroupsDN", "protocolBindDN", "protocolUserFilter", "protocolGroupFilter", "protocolEndpoints"],
  credentials: ["protocolBindPassword", "protocolClientSecret"],
  sync: ["protocolDailyTime", "protocolTimezone", "protocolSyncScope"],
  clients: ["systemApiKeyRequestsPerMinute", "systemApiKeyExpiresAt", "systemApiKeyProjectScopes", "systemApiKeyContactName"],
  ocr: ["ocrRequestTokenSettingLabel", "ocrDocumentTokenSettingLabel", "ocrDocumentTokenSettingHelp"]
};

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













function identitySyncErrorKey(errorCode: string | null): TranslationKey {
  if (errorCode === "identity_sync_queue_timeout") return "identitySyncQueueTimeout";
  if (errorCode === "identity_sync_heartbeat_timeout" || errorCode === "identity_sync_run_budget_insufficient") return "identitySyncRunTimeout";
  return "identitySyncFailed";
}

function metricPairs(metrics: OperationComponentStatus["metrics"]) {
  return Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined).slice(0, 4);
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

const nativePdfLimitFields = ["max_input_bytes", "max_request_bytes", "max_response_bytes", "context_window", "min_output_tokens", "max_output_tokens"] as const;
const nativePdfLimitLabels: Record<typeof nativePdfLimitFields[number], TranslationKey> = {
  max_input_bytes: "nativePdfMaxInput", max_request_bytes: "nativePdfMaxRequest", max_response_bytes: "nativePdfMaxResponse",
  context_window: "nativePdfContext", min_output_tokens: "nativePdfMinOutput", max_output_tokens: "nativePdfMaxOutput"
};

function nativePdfProfile(model: ModelRow | undefined): Record<string, unknown> {
  const value = model?.raw?.config?.native_pdf;
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nativePdfConfigFromForm(form: FormData, existing: ModelRow | undefined, advanced: unknown): Record<string, unknown> | null {
  const numeric = Object.fromEntries(nativePdfLimitFields.map((key) => [key, String(form.get(`native_pdf_${key}`) ?? "").trim()]));
  const hasInput = Object.values(numeric).some(Boolean);
  if (!hasInput && existing?.status === "inactive" && form.get("is_active") !== "on" && !advanced) return null;
  if (nativePdfLimitFields.some((key) => !/^\d+$/.test(numeric[key]) || !Number.isSafeInteger(Number(numeric[key])) || Number(numeric[key]) <= 0)) throw new UiValidationError("nativePdfCapabilityInvalid");
  const profile = { ...nativePdfProfile(existing), protocol: "openai_responses", mime_types: ["application/pdf"],
    supports_pdf: form.get("native_pdf_supports_pdf") === "on", count_input_tokens: form.get("native_pdf_count_input_tokens") === "on",
    supports_temperature: form.get("native_pdf_supports_temperature") === "on",
    ...Object.fromEntries(nativePdfLimitFields.map((key) => [key, Number(numeric[key])])) } as Record<string, unknown>;
  if (profile.supports_pdf !== true || profile.count_input_tokens !== true || Number(profile.min_output_tokens) > Number(profile.max_output_tokens)
      || Number(profile.max_output_tokens) >= Number(profile.context_window)) throw new UiValidationError("nativePdfCapabilityInvalid");
  if (advanced !== undefined) {
    if (!advanced || typeof advanced !== "object" || Array.isArray(advanced)) throw new UiValidationError("nativePdfConfigConflict");
    const values = advanced as Record<string, unknown>;
    for (const key of [...nativePdfLimitFields, "protocol", "mime_types", "supports_pdf", "count_input_tokens", "supports_temperature"]) {
      if (key in values && JSON.stringify(values[key]) !== JSON.stringify(profile[key])) throw new UiValidationError("nativePdfConfigConflict");
    }
    return { ...profile, ...values, ...Object.fromEntries([...nativePdfLimitFields, "protocol", "mime_types", "supports_pdf", "count_input_tokens", "supports_temperature"].map((key) => [key, profile[key]])) };
  }
  return profile;
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
  const [identityDirty, setIdentityDirty] = useState(false);
  const [settingsLeave, setSettingsLeave] = useState<(() => void) | null>(null);
  const leaveFocus = useRef<HTMLElement | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [settingsSearch, setSettingsSearch] = useState("");
  const searchText = (section: (typeof settingsSections)[number], panel: string) => [section.labelKey, settingsPanelLabels[panel], settingsPanelHelp[panel] || settingsPanelLabels[panel], ...(settingsSearchFields[panel] || [])].map(key => t(key)).join(" ").toLocaleLowerCase();
  const navigationRef = useModalFocus(narrow && navOpen && !settingsLeave, () => setNavOpen(false));
  const leaveDialogRef = useModalFocus(Boolean(settingsLeave), () => setSettingsLeave(null));
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(query.matches); update();
    query.addEventListener("change", update); return () => query.removeEventListener("change", update);
  }, []);

  const [selectedRole, setSelectedRole] = useState("");
  const [permissions, setPermissions] = useState<Record<string, PermissionState>>({});
  const [permissionSaved, setPermissionSaved] = useState(true);
  const [liveUsers, setLiveUsers] = useState<UserRow[]>([]);
  const [liveRoles, setLiveRoles] = useState<RoleRow[]>([]);
  const [liveGroupMappings, setLiveGroupMappings] = useState<GroupMappingRow[]>([]);
  const [liveModels, setLiveModels] = useState<ModelRow[]>([]);
  const [modelTableRows, setModelTableRows] = useState<ModelRow[]>([]);
  const [modelTableTotal, setModelTableTotal] = useState(0);
  const [modelTableReceived, setModelTableReceived] = useState(false);
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
    const fallback = navigationRef.current?.querySelector<HTMLButtonElement>("nav button[aria-current]");
    apiKeyDialogRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [apiKeyOneTime, modal, activeTab, navigationRef]);
  useEffect(() => {
    if (!promptEditorOpen) return;
    const trigger = systemDialogTriggerRef.current;
    const fallback = navigationRef.current?.querySelector<HTMLButtonElement>("nav button[aria-current]");
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [promptEditorOpen, navigationRef]);
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

  const canEditUsers = canEditSystemManagement;
  const canEditRoles = canEditSystemManagement;
  const canCreateRoles = canCreateSystemManagement;
  const canDeleteRoles = canDeleteSystemManagement;
  const canEditModels = canEditSystemManagement;
  const canCreateModels = canCreateSystemManagement;
  const canDeleteModels = canDeleteSystemManagement;
  const errorMessage = useCallback((error: ApiError | Error | null) => operationalErrorMessage(error, t, format), [format, t]);

  const [identityMessage, setIdentityMessage] = useState("");



  const roleMenuTriggerRef = useRef<HTMLElement | null>(null);
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
  }, [apiFetch, canViewSystemManagement, errorMessage, modelTablePage, modelTablePageSize, modelTableType]);

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
  }, [activeSection, apiFetch, liveReady, selectedRole, selectedRoleReady, selectedRoleLockVersion, permissionSaved]);



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
    return <div className="model-list-pagination"><label><span>{t("systemRowsPerPage")}</span><DropdownSelect aria-label={t("systemRowsPerPage")} disabled={busy} onChange={event => changeSize(Number(event.target.value))} value={size}>{[20, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</DropdownSelect></label><span>{total === null ? format("adminListBatch", { page: formatCount(page, locale) }) : format("systemPageOf", { page: formatCount(page, locale), total: formatCount(Math.max(1, Math.ceil(total / size)), locale) })}</span><div><button className="action-button secondary" disabled={busy || page <= 1} onClick={previous} type="button"><ChevronLeft size={15} />{t("adminPrevious")}</button><button className="action-button secondary" disabled={busy || !next} onClick={next ?? undefined} type="button">{t("adminNext")}<ChevronRight size={15} /></button></div></div>;
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
      setSubmitting(false); setDirtyModal(null); modalGuard.complete(token); setModal(null);
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

  useEffect(() => {
    const followLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.target || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (permissionSaved && !parameterDirty && !identityDirty && !promptEditorOpen && activeSection !== "identity") return;
      event.preventDefault(); event.stopPropagation();
      const go = () => {
        if (activeSection === "identity") void apiFetch(`${apiBaseUrl()}/system/identity-settings/lock`, { method: "POST" }).then(response => {
          if (!response.ok) throw new Error("identity_settings_locked"); window.location.assign(url.href);
        }).catch(error => setSystemError(error));
        else window.location.assign(url.href);
      };
      if (promptEditorOpen) requestPromptLeave(go); else requestSettingsLeave(go);
    };
    document.addEventListener("click", followLink, true);
    return () => document.removeEventListener("click", followLink, true);
  });

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
      identitySourceLabel(user.source, t)
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
    await runModalMutation(() => updateUser(apiFetch, modal.user.id, payload), updated => { setLiveUsers(current => current.map(user => user.id === updated.id ? userRow(updated) : user)); }, "systemUserLocalFieldsSaved");
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
      if (modelType === "OCR" && provider === "OpenAI") {
        const profile = nativePdfConfigFromForm(formData, modal?.type === "model" ? modal.model : undefined, config.native_pdf);
        if (profile) config.native_pdf = profile;
      }
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
      const pricingKeys = ["input_cost_per_million_tokens", "output_cost_per_million_tokens", "embedding_cost_per_million_tokens"];
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




  if (loadedSystemScope !== systemReadScope) return <FeedbackMessage tone="info">{t("loadingData")}</FeedbackMessage>;

  return (
    <section className="system-workspace">
      {systemLoading ? <div className="fixture-banner"><Settings2 size={17} /><div><strong>{t("loadingData")}</strong><span>{t("systemLoadingBackend")}</span></div></div> : null}
      {quickError ? <FeedbackMessage tone={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? "warning" : "error"} actions={quickOperation.phase === "unknown" || quickOperation.phase === "read_failed" ? <button type="button" className="action-button secondary" disabled={quickOperation.checking} onClick={() => void queryQuickOutcome()}>{t("feedbackQueryOutcome")}</button> : undefined}><strong>{quickOperation.checking ? t("feedbackCheckingOutcome") : quickOperation.phase === "read_failed" ? t("feedbackAcceptedReadFailed") : quickOperation.phase === "unknown" ? t("feedbackResultUnknown") : errorMessage(quickError)}</strong>{quickQueryFailed ? <p>{t("feedbackOutcomeQueryFailed")}</p> : null}{quickOperation.phase === "unknown" && quickOperation.checked ? <p>{t("feedbackSystemOutcomeChecked")}</p> : null}</FeedbackMessage> : null}
      {systemError ? <FeedbackMessage tone="error"><strong>{errorMessage(systemError)}</strong><button className="text-link" onClick={loadSystem} type="button">{t("retry")}</button></FeedbackMessage> : null}
      {settingsLeave ? <div className="system-modal-backdrop"><section ref={leaveDialogRef} role="alertdialog" aria-modal="true" aria-labelledby="settings-leave-title" className="system-reauth-modal"><h2 id="settings-leave-title">{t("contentEditUnsaved")}</h2><FeedbackConfirm title={t("settingsLeaveHelp")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => { setSettingsLeave(null); leaveFocus.current?.focus(); }} onConfirm={() => { const action = settingsLeave; setSettingsLeave(null); if (!permissionSaved) setPermissions(previous => { const next = { ...previous }; delete next[selectedRole]; return next; }); action(); }} /></section></div> : null}
      <button className="action-button secondary settings-menu-trigger" aria-expanded={navOpen} aria-controls="settings-navigation" onClick={() => setNavOpen(true)} type="button"><Settings2 size={18} />{t("settingsCategories")}</button>
      <div className="system-settings-layout">
        {narrow && navOpen ? <div className="settings-nav-backdrop" onClick={() => setNavOpen(false)} /> : null}
        <aside id="settings-navigation" ref={navigationRef} inert={Boolean(settingsLeave)} role={narrow && navOpen && !settingsLeave ? "dialog" : undefined} aria-modal={narrow && navOpen && !settingsLeave ? true : undefined} aria-label={t("settingsCategories")} className={`settings-navigation${navOpen ? " is-open" : ""}`}>
          <div className="settings-nav-heading"><strong>{t("settingsCategories")}</strong><button className="icon-button settings-menu-close" aria-label={t("close")} onClick={() => setNavOpen(false)} type="button"><X size={18} /></button></div>
          <label className="settings-search"><Search size={16} /><input type="search" value={settingsSearch} aria-label={t("settingsSearch")} placeholder={t("settingsSearch")} onChange={event => setSettingsSearch(event.target.value)} /></label>
          <nav aria-label={t("settingsCategories")}>{settingsSections.map((section, index) => {
            const Icon = [UsersRound, ShieldCheck, Bot, Layers3, KeyRound, SlidersHorizontal, Activity][index];
            return <button type="button" key={section.id} aria-current={activeSection === section.id ? "page" : undefined} onClick={() => navigateSettings({ section: section.id, panel: section.panels[0] })}><Icon size={18} /><span>{t(section.labelKey)}</span><ChevronRight size={15} /></button>;
          })}</nav>
          {settingsSearch.trim() ? <div className="settings-search-results" aria-live="polite">{settingsSections.flatMap(section => section.panels.map(panel => ({ section, panel, label: t(settingsPanelLabels[panel]) }))).filter(item => searchText(item.section, item.panel).includes(settingsSearch.trim().toLocaleLowerCase())).map(item => <button type="button" key={item.panel} onClick={() => { navigateSettings({ section: item.section.id, panel: item.panel }); }}><span>{t(item.section.labelKey)}</span><strong>{item.label}</strong></button>)}{!settingsSections.some(section => section.panels.some(panel => searchText(section, panel).includes(settingsSearch.trim().toLocaleLowerCase()))) ? <p>{t("settingsSearchEmpty")}</p> : null}</div> : null}
        </aside>
        <div className="settings-main" inert={Boolean(settingsLeave) || narrow && navOpen}>
          <header className="settings-page-heading"><p>{t("labelSystemManagement")}</p><h1>{t(settingsSections.find(section => section.id === activeSection)!.labelKey)}</h1><span>{t("settingsWorkspaceHelp")}</span></header>
          {activeSection === "general" ? <button type="button" className="text-link" onClick={() => navigateSettings({ section: "documents", panel: "upload" })}>{t("settingsGoDocuments")}<ChevronRight size={16} /></button> : null}
          {(activeSection === "people" ? ["users", "roles", "groups", "mappings"] : activeSection === "ai" ? ["models", "prompts"] : activeSection === "apiKeys" ? ["clients", "projects"] : activeSection === "status" ? ["status"] : []).map(section => <div key={section}>{renderSectionReadNotice(section)}</div>)}
          {activeSection === "people" ? <SettingsCard panel="users">
            <SectionHeader action={<button className="action-button secondary" disabled={!canEditUsers} onClick={runIdentitySync} type="button"><RefreshCw size={16} />{t("systemSyncNow")}</button>} description={t("systemUserManagementDescription")} title={t("systemUserManagementTitle")} />
            <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchUsers")} maxLength={100} onChange={(event) => { setUserQuery(event.target.value); setUserPage(1); }} placeholder={t("systemSearchUsersPlaceholder")} value={userQuery} /></label><DropdownSelect aria-label={t("systemFilterIdentitySource")} onChange={(event) => { setUserSourceFilter(event.target.value); setUserPage(1); }} value={userSourceFilter}><option value="all">{t("systemAllIdentitySources")}</option>{Array.from(new Set(["ldap", "ad", "local", ...liveUsers.map(user => user.source), ...(userSourceFilter === "all" ? [] : [userSourceFilter])])).map((source) => <option key={source} value={source}>{identitySourceLabel(source, t)}</option>)}</DropdownSelect><span>{format("systemUserCount", { filtered: sectionReads.users?.received ? formatCount(filteredUsers.length, locale) : t("systemReadCountUnknown"), total: sectionReads.users?.received ? formatCount(userTotal, locale) : t("systemReadCountUnknown") })}</span></div>
            {filteredUsers.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemUser")}</th><th>{t("systemDepartment")}</th><th>{t("systemIdentitySourceColumn")}</th><th>{t("systemRoleColumn")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{filteredUsers.map((user) => <tr key={user.id}><td><strong>{userRowName(user)}</strong><small>{user.email}</small></td><td>{user.department}</td><td>{identitySourceLabel(user.source, t)}</td><td>{user.roles}</td><td><StateBadge tone={user.status === "active" ? "green" : "gray"}>{localizedStatus(user.status)}</StateBadge></td><td><div className="system-row-actions"><button aria-label={format("systemViewUser", { name: userRowName(user) })} className="icon-text-button" onClick={() => setModal({ type: "user", user })} type="button">{t("systemView")} <ChevronRight size={15} /></button><button className="icon-text-button" disabled={!canEditUsers} onClick={() => setModal({ type: "confirm", title: `${user.status === "active" ? t("systemDisable") : t("systemEnable")}${t("systemUser")}`, message: format("systemConfirmToggleUser", { action: user.status === "active" ? t("systemDisable") : t("systemEnable"), name: userRowName(user) }), actionLabel: user.status === "active" ? t("systemDisable") : t("systemEnable"), target: { kind: "user", id: user.id, expected: { field: "is_active", value: user.status !== "active" } }, run: accepted => toggleUser(user, accepted) })} type="button">{user.status === "active" ? t("systemDisable") : t("systemEnable")}</button></div></td></tr>)}</tbody></table></div> : sectionReady("users") ? <EmptyInlineState /> : null}
            {renderListPager("users", userPage, userPageSize, userTotal, () => setUserPage(page => page - 1), userPage * userPageSize < userTotal ? () => setUserPage(page => page + 1) : null, size => { setUserPageSize(size); setUserPage(1); })}
          </SettingsCard> : null}

          {activeSection === "people" ? <SettingsCard panel="roles">
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
          </SettingsCard> : null}

          {activeSection === "people" ? <SettingsCard panel="permissions">
            <SectionHeader action={<div className="system-save-state"><span>{permissionSaved ? <><Check size={15} />{t("systemSaved")}</> : t("systemUnsavedChanges")}</span><button className="action-button" disabled={!canEditPermissions || selectedRoleReadOnly || !sectionReady("roles") || !permissions[selectedRole]} onClick={savePermissions} title={!canEditPermissions ? t("apiForbidden") : selectedRoleReadOnly ? t("systemRoleReadOnly") : undefined} type="button"><Save size={16} />{t("systemSavePermissions")}</button></div>} description={t("systemPermissionsDescription")} title={t("systemPermissions")} />
            <div className="system-toolbar"><label><Search size={16} /><input aria-label={t("systemSearchRoles")} maxLength={100} onChange={event => { setRoleQuery(event.target.value); setRolePage(1); }} value={roleQuery} /></label></div>
            {renderListPager("roles", rolePage, rolePageSize, roleTotal, () => setRolePage(page => page - 1), rolePage * rolePageSize < roleTotal ? () => setRolePage(page => page + 1) : null, size => { setRolePageSize(size); setRolePage(1); })}
            <div className="role-selector" aria-label={t("systemSelectRole")}>{filteredLocalRoles.map((role) => <button aria-pressed={selectedRole === role.id} className={`${selectedRole === role.id ? "active" : ""}${role.isActive === false ? " inactive" : ""}`} key={role.id} onClick={() => requestSettingsLeave(() => { setSelectedRole(role.id); setPermissionSaved(true); })} type="button"><span>{role.name}</span><small>{format("systemRoleSelectorSummary", { members: role.members ?? t("systemReadCountUnknown"), groups: role.groups ?? t("systemReadCountUnknown") })} · {role.isActive === false ? t("systemDisabled") : t("systemEnabled")}</small></button>)}</div>
            {selectedRoleReadOnly ? <FeedbackMessage tone="info"><div><strong>{t("systemRoleReadOnly")}</strong><p>{t("systemRolePermissionsReadOnlyHelp")}</p></div></FeedbackMessage> : null}
            {liveRoles.length ? <div className="permission-matrix-wrap"><table className="permission-matrix-table"><thead><tr><th>{t("systemMenuPermission")}</th><th>{t("permissionActionView")}</th><th>{t("permissionActionCreate")}</th><th>{t("permissionActionEdit")}</th><th>{t("permissionActionDelete")}</th><th>{t("permissionActionExecute")}</th></tr></thead><tbody>{permissionMenuRows.map((row) => { const state = permissions[selectedRole]?.[row.key] ?? emptyPermissionState()[row.key]; return <tr key={row.key}><td><strong>{t(row.labelKey as TranslationKey)}</strong><small>{t(row.descriptionKey as TranslationKey)}</small></td>{(["view", "create", "edit", "delete", "execute"] as PermissionAction[]).map((action) => { const enabled = permissionActionEnabled(row, action); return <td key={action}>{!enabled ? <span aria-label={t("settingsNotApplicable")}>—</span> : <input aria-label={`${liveRoles.find((role) => role.id === selectedRole)?.name ?? t("systemRoleColumn")} ${t(row.labelKey as TranslationKey)} ${t(`permissionAction${action.charAt(0).toUpperCase()}${action.slice(1)}` as TranslationKey)}`} checked={enabled && state[action]} disabled={!canEditPermissions || selectedRoleReadOnly || !enabled || !sectionReady("roles") || !permissions[selectedRole]} onChange={() => togglePermission(row.key, action)} type="checkbox" />}</td>; })}</tr>; })}</tbody></table></div> : <EmptyInlineState />}
          </SettingsCard> : null}

          {activeSection === "ai" ? <SettingsCard panel="models">
            <SectionHeader action={<button className="action-button" disabled={!canCreateModels || !sectionReady("models")} onClick={() => openModelModal()} type="button"><Bot size={16} />{t("systemAddModel")}</button>} description={t("systemModelsDescription")} title={t("systemModels")} />
            <div className="model-list-toolbar">
              <label><span>{t("systemModelTypeFilter")}</span><DropdownSelect aria-label={t("systemModelTypeFilter")} onChange={(event) => { setModelTableType(event.target.value); setModelTablePage(1); }} value={modelTableType}><option value="all">{t("systemAllModelTypes")}</option><option value="Chat">{t("labelChat")}</option><option value="Embedding">Embedding</option><option value="OCR">OCR</option><option value="Judge">Judge</option></DropdownSelect></label>
              <span aria-live="polite">{format("systemModelResultRange", { first: modelTableReceived ? modelTableFirst : t("systemReadCountUnknown"), last: modelTableReceived ? modelTableLast : t("systemReadCountUnknown"), total: modelTableReceived ? modelTableTotal : t("systemReadCountUnknown") })}</span>
            </div>
            {modelTableError ? <FeedbackMessage tone="error"><strong>{localize(modelTableError)}</strong><button className="icon-text-button" onClick={() => { void refreshModelTable(); }} type="button"><RefreshCw size={14} />{t("retry")}</button></FeedbackMessage> : null}
            {modelTableLoading ? <div className="system-table-loading" role="status"><LoaderCircle className="spin" size={20} /><span>{t("systemLoadingModels")}</span></div> : null}
            {!modelTableLoading && modelTableRows.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemName")}</th><th>{t("systemModelType")}</th><th>{t("labelProvider")}</th><th>{t("systemModel")}</th><th>{t("systemSecret")}</th><th>{t("systemStatusColumn")}</th><th aria-label={t("systemActionsColumn")} /></tr></thead><tbody>{modelTableRows.map((model) => {
              const modelIsActive = model.status === "active";
              return <tr key={model.id}><td><strong>{model.name}</strong>{model.default ? <small>{format("systemDefaultModelLabel", { type: model.type })}</small> : null}</td><td>{model.type}</td><td>{model.provider}</td><td>{aiModelProviderName(model.raw?.config)}</td><td><span className="secret-state"><LockKeyhole size={14} />{model.raw?.api_key_configured || model.raw?.api_key_secret_ref ? t("systemConfigured") : t("systemNotConfigured")}</span></td><td><div className="model-status-stack"><StateBadge tone={modelIsActive ? "green" : "gold"}>{localizedStatus(model.status)}</StateBadge>{model.raw?.last_test_status ? <><StateBadge tone={model.raw.last_test_status === "success" ? "green" : model.raw.last_test_status === "failed" ? "coral" : "gold"}>{localizedOperationStatus(model.raw.last_test_status)}</StateBadge><small>{model.raw.last_tested_at ? new Date(model.raw.last_tested_at).toLocaleString() : null}{model.raw.last_test_latency_ms !== null ? ` · ${model.raw.last_test_latency_ms} ms` : ""}</small></> : <small>{t("systemConnectionNotTested")}</small>}</div></td><td><div className="system-row-actions"><button className="icon-text-button" disabled={!canEditModels} onClick={() => openModelModal(model)} type="button">{t("systemEdit")}</button><button className="icon-text-button" disabled={!canEditModels || quickBlocked || model.default || !modelIsActive} onClick={() => { void runQuickMutation({ kind: "model", id: model.id, field: "is_default", value: true }, () => setDefaultModel(apiFetch, model.id), refreshModels); }} type="button">{t("systemSetDefault")}</button><button className="icon-text-button" disabled={!canEditModels} onClick={() => { void runModelConnectionTest(model); }} type="button">{t("systemTest")}</button>{modelIsActive ? <button className="icon-text-button" disabled={!canEditModels} onClick={() => setModal({ type: "confirm", title: t("systemDisableModel"), message: t("systemDisableModelHelp"), actionLabel: t("systemDisable"), successTitle: "systemModelDeactivated", target: { kind: "model", id: model.id, expected: { field: "is_active", value: false } }, run: accepted => deactivateModelRow(model, accepted) })} type="button">{t("systemDisable")}</button> : <button className="icon-text-button" disabled={!canEditModels || quickBlocked} onClick={() => { void activateModel(model); }} type="button">{t("systemEnable")}</button>}<button aria-label={format("systemDeleteModelAria", { name: model.name })} className="icon-text-button destructive" disabled={!canDeleteModels} onClick={() => openModelDeleteModal(model)} type="button"><Trash2 size={14} />{t("systemDelete")}</button></div></td></tr>;
            })}</tbody></table></div> : null}
            {!modelTableLoading && !modelTableRows.length && !modelTableError ? <EmptyInlineState>{t("systemNoModelsMatchFilter")}</EmptyInlineState> : null}
            <div className="model-list-pagination">
              <label><span>{t("systemRowsPerPage")}</span><DropdownSelect aria-label={t("systemRowsPerPage")} onChange={(event) => { setModelTablePageSize(Number(event.target.value)); setModelTablePage(1); }} value={modelTablePageSize}><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></DropdownSelect></label>
              <span>{format("systemPageOf", { page: modelTablePage, total: modelTableTotalPages })}</span>
              <div><button aria-label={t("systemPreviousPage")} className="icon-button" disabled={modelTableLoading || modelTablePage <= 1} onClick={() => setModelTablePage((page) => Math.max(1, page - 1))} type="button"><ChevronLeft size={17} /></button><button aria-label={t("systemNextPage")} className="icon-button" disabled={modelTableLoading || modelTablePage >= modelTableTotalPages} onClick={() => setModelTablePage((page) => Math.min(modelTableTotalPages, page + 1))} type="button"><ChevronRight size={17} /></button></div>
            </div>
          </SettingsCard> : null}

          {activeSection === "ai" ? <SettingsCard panel="prompts">
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
              <div className="system-subsection-title"><div><h3><Bot size={18} />{t("systemPromptModelSection")}</h3><p>{t("systemPromptModelSectionHelp")}</p></div><div className="system-toolbar compact"><DropdownSelect aria-label={t("systemPromptSelectModel")} onChange={(event) => setPromptModelDraft(event.target.value)} value={promptModelDraft}>{promptModelOptions.length ? promptModelOptions.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.type}</option>) : <option value="">{t("systemPromptNoModelsAvailable")}</option>}</DropdownSelect><button className="action-button secondary" disabled={!canCreateModels || !promptModelDraft || promptSaving || !sectionReady("prompts") || !sectionReady("models")} onClick={() => { void createModelPrompt(); }} type="button"><Plus size={16} />{t("systemPromptAddModel")}</button></div></div>
              {modelSpecificPrompts.length ? <div className="system-table-wrap system-prompt-model-table"><table className="system-table"><thead><tr><th>{t("systemModel")}</th><th>{t("systemModelType")}</th><th>{t("systemVersion")}</th><th>{t("systemStatusColumn")}</th></tr></thead><tbody>{modelSpecificPrompts.map((prompt) => <tr className={selectedPromptId === prompt.id ? "selected-row" : ""} key={prompt.id} onClick={() => selectPrompt(prompt)}><td><button className="text-link system-prompt-open" type="button" onClick={(event) => { event.stopPropagation(); selectPrompt(prompt); }} aria-label={format("systemPromptOpenForModel", { name: liveModels.find(model => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—" })}><MessageSquareText size={16} aria-hidden="true" /><strong>{liveModels.find((model) => model.id === prompt.model_id)?.name ?? prompt.model_id ?? "—"}</strong></button><small>{prompt.content_hash ?? t("systemPromptBlankHash")}</small></td><td>{prompt.model_type}</td><td>{prompt.current_version_number ?? "—"}</td><td><StateBadge tone={prompt.is_active ? "green" : "gray"}>{prompt.is_active ? t("systemEnabled") : t("systemDisabled")}</StateBadge></td></tr>)}</tbody></table></div> : sectionReady("prompts") ? <EmptyInlineState>{t("systemPromptNoModelPrompts")}</EmptyInlineState> : null}
            </section>
          </SettingsCard> : null}

          {activeSection === "apiKeys" ? <SettingsCard panel="clients">
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
          </SettingsCard> : null}

          {activeTab === "identity" ? <>
            <ProtocolIdentityPanel key={systemReadScope} canEdit={canEditSystemManagement} onDirtyChange={setIdentityDirty} />
            <section className="identity-settings-section settings-card" id="settings-panel-emergency" tabIndex={-1} aria-labelledby="identity-emergency-title">
              {renderSectionReadNotice("breakGlass")}
              <div className="system-subsection-title"><h3 id="identity-emergency-title">{t("identityEmergencyAccess")}</h3><StateBadge tone={breakGlassTone(breakGlassStatus?.status)}>{localizedBreakGlassStatus(breakGlassStatus?.status)}</StateBadge></div>
              <p>{t("identityBreakGlassHelp")}</p>
              <dl className="identity-oidc-meta">
                <div><dt>{t("protocolUsername")}</dt><dd>{breakGlassStatus?.username || t("systemReadCountUnknown")}</dd></div>
                <div><dt>{t("identityBreakGlassNormalState")}</dt><dd>{breakGlassNormalStateText(breakGlassStatus, t)}</dd></div>
                <div><dt>{t("identityBreakGlassSystemAdmin")}</dt><dd>{evidenceText(breakGlassStatus?.system_admin_mapped, t)}</dd></div>
                <div><dt>{t("identityCredential")}</dt><dd>{breakGlassStatus?.credential_source === "deployment_secret" ? t("identityDeploymentSecret") : t("identityNotVerified")}</dd></div>
                <div><dt>{t("identityCredentialUpdate")}</dt><dd>{breakGlassStatus?.credential_update_required === true ? t("identityRequired") : breakGlassStatus?.credential_update_required === false ? t("protocolNotRequired") : t("identityNotVerified")}</dd></div>
                <div><dt>{t("identityLifecycleControl")}</dt><dd>{evidenceStateText(breakGlassStatus?.lifecycle_control, t)}</dd></div>
                <div><dt>{t("identityRunbookEvidence")}</dt><dd>{evidenceStateText(breakGlassStatus?.runbook_evidence, t)}</dd></div>
                <div><dt>{t("identityAlertingEvidence")}</dt><dd>{evidenceStateText(breakGlassStatus?.alerting_evidence, t)}</dd></div>
              </dl>
              {breakGlassStatus?.checked_at ? <p>{format("identityBreakGlassCheckedAt", { time: new Date(breakGlassStatus.checked_at).toLocaleString(locale) })}</p> : null}
            </section>
          </> : null}

          {activeTab === "status" ? <>
            <SectionHeader action={<button className="action-button secondary" onClick={() => { void refreshSystemStatus(); }} type="button"><RefreshCw size={16} />{t("refresh")}</button>} description={t("systemStatusDescription")} title={t("systemStatus")} />
            <div className="fixture-banner"><Activity size={17} /><div><strong>{t("liveData")}</strong><span>{t("systemStatusLiveHelp")}</span></div></div>
            {systemStatus ? <>
              <SettingsCard panel="runtime" title={t("settingsRuntime")}><div className="system-status-grid">
              {[
                systemStatus.worker,
                systemStatus.queue,
                systemStatus.retrieval
              ].map((component) => <article className="system-status-card" key={component.name}><header><div><small>{component.name}</small><h3>{component.detail_code}</h3></div><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></header><dl>{metricPairs(component.metrics).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl><small>{format("systemCheckedAt", { time: component.checked_at.slice(0, 16).replace("T", " ") })}</small></article>)}
              </div>
              </SettingsCard><div className="system-status-columns">
              <SettingsCard panel="dependencies" title={t("systemDependencies")}>
                <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemComponent")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemChecked")}</th></tr></thead><tbody>{systemStatus.dependencies.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></td><td>{component.detail_code}</td><td>{component.checked_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div>
              </SettingsCard>
              <SettingsCard panel="providers" title={t("systemAiProviders")}>
                <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemProviderRole")}</th><th>{t("systemStatusColumn")}</th><th>{t("systemDetail")}</th><th>{t("systemMetrics")}</th></tr></thead><tbody>{systemStatus.providers.map((component) => <tr key={component.name}><td><strong>{component.name}</strong></td><td><StateBadge tone={statusTone(component.status)}>{localizedOperationStatus(component.status)}</StateBadge></td><td>{component.detail_code}</td><td>{metricPairs(component.metrics).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "—"}</td></tr>)}</tbody></table></div>
              </SettingsCard>
              </div>
              <SettingsCard panel="errors" title={t("systemRecentErrors")}>
              {systemStatus.recent_errors.length ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemSourceColumn")}</th><th>{t("systemAction")}</th><th>{t("systemResult")}</th><th>{t("systemCode")}</th><th>{t("systemTime")}</th></tr></thead><tbody>{systemStatus.recent_errors.map((error) => <tr key={`${error.source}-${error.action}-${error.created_at}`}><td>{error.source}</td><td>{error.action}</td><td><StateBadge tone={statusTone(error.result === "success" ? "healthy" : "degraded")}>{localizedOperationStatus(error.result)}</StateBadge></td><td>{error.detail_code}</td><td>{error.created_at.slice(0, 16).replace("T", " ")}</td></tr>)}</tbody></table></div> : <div className="empty-inline-state"><Check size={18} />{t("systemNoRecentErrors")}</div>}
              </SettingsCard>
            </> : sectionReady("status") ? <EmptyInlineState>{t("systemStatusUnavailable")}</EmptyInlineState> : null}
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
            <div className="system-detail-grid"><div><small>{t("systemName")}</small><strong>{userRowName(modal.user)}</strong></div><div><small>{t("labelEmail")}</small><strong>{modal.user.email}</strong></div><div><small>{t("systemSourceColumn")}</small><strong>{identitySourceLabel(modal.user.source, t)}</strong></div><div><small>{t("systemStatusColumn")}</small><strong>{localizedStatus(modal.user.status)}</strong></div></div>
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
            <div className="system-mapping-editor"><label><span>{t("systemLdapGroup")}<small>{t("systemOneToOneMappingHelp")}</small></span><DropdownSelect autoFocus disabled={modal.role.isActive === false || !canEditRoles} onChange={(event) => setMappingGroupDraft(event.target.value)} value={mappingGroupDraft}><option value="">{t("systemNoMapping")}</option>{availableMappingGroups.map((group) => <option key={group.id} value={group.id}>{group.path || group.group_name} · {format("systemMemberCount", { count: group.member_count })}</option>)}</DropdownSelect></label></div>
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
              <label><span>{t("systemModelType")}</span><DropdownSelect disabled={Boolean(modal.model)} name="model_type" onChange={(event) => { setModelTypeDraft(event.target.value); if (event.target.value === "OCR" && !modal.model) setModelProviderDraft("OpenAI"); }} value={modelTypeDraft}><option value="Chat">{t("labelChat")}</option><option>Embedding</option><option value="OCR">{t("labelPdfRecognition")}</option><option>Judge</option></DropdownSelect>{modal.model ? <input name="model_type" type="hidden" value={modal.model.type} /> : null}</label>
              <label><span>{t("labelProvider")}</span><DropdownSelect name="provider" onChange={(event) => setModelProviderDraft(event.target.value)} value={modelProviderDraft}>{aiProviders.filter((provider) => modelTypeDraft !== "OCR" || provider.id === "OpenAI" || provider.id === modal.model?.provider).map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</DropdownSelect></label>
              <label><span>{t("labelModelName")}</span><input defaultValue={modelConfigValue(modal.model, "model_name")} name="model_name" placeholder={modelProviderDraft === "Ollama" ? "llama3.1" : modelProviderDraft === "Gemini" ? "gemini-1.5-pro" : modelProviderDraft === "Claude" ? "claude-3-5-sonnet-latest" : t("systemModelNamePlaceholder")} required={modelProviderDraft !== "Custom"} /></label>
            </div>
            {modelProviderDraft === "OpenAI" ? <div className="identity-form-grid settings-child-fields">
              <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "https://api.openai.com/v1")} name="base_url" /></label>
              <label><span>{t("systemOrganizationIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "organization_id")} name="organization_id" /></label>
              <label><span>{t("systemProjectIdOptional")}</span><input defaultValue={modelConfigValue(modal.model, "project_id")} name="project_id" /></label>
              <OpenAiApiModeField existingMode={modelConfigValue(modal.model, "api_mode")} isExisting={Boolean(modal.model)} modelType={modelTypeDraft} />
              {modelTypeDraft === "Embedding" ? <label><span>{t("systemEmbeddingDimensionOptional")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_dimension")} min={1} name="embedding_dimension" type="number" /></label> : null}
            </div> : null}
            {modelProviderDraft === "Gemini" ? <div className="identity-form-grid settings-child-fields"><label><span>{t("labelApiVersion")}</span><input defaultValue={modelConfigValue(modal.model, "api_version", "v1beta")} name="api_version" /></label></div> : null}
            {modelProviderDraft === "Claude" ? <div className="identity-form-grid settings-child-fields">
              <label><span>{t("systemBaseUrlOptional")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "")} name="base_url" placeholder="https://api.anthropic.com" /></label>
              <label><span>Anthropic-Version</span><input defaultValue={modelConfigValue(modal.model, "anthropic_version", "2023-06-01")} name="anthropic_version" /></label>
            </div> : null}
            {modelProviderDraft === "Ollama" ? <div className="identity-form-grid settings-child-fields">
              <label><span>{t("labelBaseUrl")}</span><input defaultValue={modelConfigValue(modal.model, "base_url", modal.model?.endpoint || "http://127.0.0.1:11434")} name="base_url" required /></label>
              <label><span>{t("labelTimeoutSeconds")}</span><input defaultValue={modelConfigValue(modal.model, "timeout_seconds", "120")} min={1} name="timeout_seconds" type="number" /></label>
            </div> : null}
            {modelProviderDraft === "vLLM" ? <div className="identity-form-grid settings-child-fields">
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
                {(modelTypeDraft === "Chat" || modelTypeDraft === "Judge" || modelTypeDraft === "OCR") ? <>
                  <label><span>{t("systemModelInputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "input_cost_per_million_tokens")} min="0" name="input_cost_per_million_tokens" step="any" type="number" /></label>
                  <label><span>{t("systemModelOutputPrice")}</span><input defaultValue={modelConfigValue(modal.model, "output_cost_per_million_tokens")} min="0" name="output_cost_per_million_tokens" step="any" type="number" /></label>
                </> : null}
                {modelTypeDraft === "Embedding" ? <label><span>{t("systemModelEmbeddingPrice")}</span><input defaultValue={modelConfigValue(modal.model, "embedding_cost_per_million_tokens")} min="0" name="embedding_cost_per_million_tokens" step="any" type="number" /></label> : null}
                <label><span>{t("systemModelCostCurrency")}</span><DropdownSelect defaultValue={modelConfigValue(modal.model, "cost_currency")} name="cost_currency"><option value="">{t("systemModelCostCurrencyPlaceholder")}</option>{["TWD", "USD", "JPY", "EUR", "GBP", "CNY", "HKD", "SGD", "AUD", "CAD", "KRW"].map((currency) => <option key={currency}>{currency}</option>)}</DropdownSelect></label>
              </div>
            </div>
            <label><span>{t("systemApiKeyRetainExisting")}</span><input autoComplete="new-password" disabled={modelCredentialClearDraft} name="api_key" type="password" /></label>
            <label><span>{t("labelSecretReference")}</span><input defaultValue={modal.model?.raw?.api_key_secret_ref ?? ""} disabled={modelCredentialClearDraft} name="api_key_secret_ref" placeholder={t("systemSecretReferencePlaceholder")} /></label>
            <AIModelCredentialClearControl clearDraft={modelCredentialClearDraft} configured={Boolean(modal.model?.raw?.api_key_configured)} confirmation={modelCredentialClearConfirmation} modelName={modal.model?.name ?? ""} onClearChange={(checked) => { setModelCredentialClearDraft(checked); setModelCredentialClearConfirmation(""); }} onConfirmationChange={setModelCredentialClearConfirmation} />
            {modelTypeDraft === "OCR" && modelProviderDraft === "OpenAI" ? <fieldset className="native-pdf-capability-form"><legend>{t("nativePdfCapabilitiesTitle")}</legend><small>{t("nativePdfCapabilitiesHelp")}</small><div className="identity-form-grid">
              <label><span>{t("nativePdfProtocol")}</span><input readOnly value="openai_responses" /></label><label><span>{t("nativePdfMime")}</span><input readOnly value="application/pdf" /></label>
              {nativePdfLimitFields.map((key) => <label key={key}><span>{t(nativePdfLimitLabels[key])}</span><input defaultValue={typeof nativePdfProfile(modal.model)[key] === "number" ? String(nativePdfProfile(modal.model)[key]) : ""} min={1} name={`native_pdf_${key}`} step={1} type="number" /></label>)}
              <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).supports_pdf === true} name="native_pdf_supports_pdf" type="checkbox" /><span>{t("nativePdfSupportsPdf")}</span></label>
              <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).count_input_tokens === true} name="native_pdf_count_input_tokens" type="checkbox" /><span>{t("nativePdfSupportsCount")}</span></label>
              <label className="identity-toggle"><input defaultChecked={nativePdfProfile(modal.model).supports_temperature === true} name="native_pdf_supports_temperature" type="checkbox" /><span>{t("nativePdfSupportsTemperature")}</span></label>
            </div></fieldset> : null}
            <label><span>{t("systemAdvancedConfigJson")}</span><textarea defaultValue={JSON.stringify(Object.fromEntries(Object.entries(modal.model?.raw?.config ?? {}).filter(([key]) => modelTypeDraft !== "OCR" || key !== "native_pdf")), null, 2)} name="config_advanced" rows={5} /><small>{t("systemAdvancedConfigHelp")}</small>{modelTypeDraft === "Embedding" ? <small>{t("systemEmbeddingCapacityHelp")}</small> : null}{modelTypeDraft === "OCR" ? <><small>{t("systemNativePdfProviderHelp")}</small><small>{t("systemNativePdfProfileHelp")}</small></> : null}</label>
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
