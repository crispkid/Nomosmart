export const systemTabIds = [
  "users",
  "roles",
  "permissions",
  "models",
  "prompts",
  "apiKeys",
  "identity",
  "status",
  "parameters"
] as const;

export type SystemTabId = (typeof systemTabIds)[number];
export type IdentityReauthResult = "pending" | "success" | "cancelled" | "error";

const systemTabIdSet = new Set<string>(systemTabIds);
const identityReauthResultSet = new Set<string>(["pending", "success", "cancelled", "error"]);

function singleSearchParam(value: string | string[] | null | undefined): string | null {
  return typeof value === "string" ? value : null;
}

export function parseSystemTab(value: string | string[] | null | undefined): SystemTabId {
  const candidate = singleSearchParam(value);
  return candidate && systemTabIdSet.has(candidate) ? candidate as SystemTabId : "users";
}

export function parseIdentityReauthResult(
  value: string | string[] | null | undefined
): IdentityReauthResult | null {
  const candidate = singleSearchParam(value);
  return candidate && identityReauthResultSet.has(candidate)
    ? candidate as IdentityReauthResult
    : null;
}

export function systemRouteUrl(
  currentUrl: string,
  tab: SystemTabId,
  reauth: IdentityReauthResult | null | undefined = undefined
): string {
  const url = new URL(currentUrl, "http://nomosmart.local");
  url.searchParams.set("tab", tab);
  if (reauth === null) url.searchParams.delete("reauth");
  if (reauth !== undefined && reauth !== null) url.searchParams.set("reauth", reauth);
  return `${url.pathname}${url.search}${url.hash}`;
}

// CHG-389: one workspace, section navigation and scroll targets (never a second tab row).
export const settingsSections = [
  { id: "people", labelKey: "settingsPeople", panels: ["users", "roles", "permissions"] },
  { id: "identity", labelKey: "settingsIdentity", panels: ["login", "directory", "credentials", "sync", "sync-history", "emergency"] },
  { id: "ai", labelKey: "settingsAI", panels: ["models", "prompts"] },
  { id: "documents", labelKey: "settingsDocuments", panels: ["upload", "retention", "ocr"] },
  { id: "apiKeys", labelKey: "settingsApiKeys", panels: ["clients"] },
  { id: "general", labelKey: "settingsGeneral", panels: ["time", "drafts"] },
  { id: "status", labelKey: "settingsStatus", panels: ["runtime", "dependencies", "providers", "errors"] }
] as const;
export type SettingsSection = (typeof settingsSections)[number]["id"];
export type SettingsPosition = { section: SettingsSection; panel: string };
export const legacySettingsPositions: Record<SystemTabId, SettingsPosition> = {
  users: { section: "people", panel: "users" }, roles: { section: "people", panel: "roles" },
  permissions: { section: "people", panel: "permissions" }, models: { section: "ai", panel: "models" },
  prompts: { section: "ai", panel: "prompts" }, apiKeys: { section: "apiKeys", panel: "clients" },
  identity: { section: "identity", panel: "login" }, status: { section: "status", panel: "runtime" },
  parameters: { section: "general", panel: "time" }
};
export function parseSettingsPosition(query: Record<string, string | string[] | null | undefined>): SettingsPosition {
  // Authentication completion is processed by the existing identity flow first.
  if (query.tab === "identity" && typeof query.reauth === "string") return legacySettingsPositions.identity;
  const section = settingsSections.find(item => item.id === query.section);
  if (section) return { section: section.id, panel: typeof query.panel === "string" && (section.panels as readonly string[]).includes(query.panel) ? query.panel : section.panels[0] };
  return legacySettingsPositions[parseSystemTab(query.tab)];
}
export function settingsPositionUrl(currentUrl: string, position: SettingsPosition): string {
  const url = new URL(currentUrl, "http://nomosmart.local");
  const query = new URLSearchParams({ section: position.section, panel: position.panel });
  // No field values, free return URL, search terms or auth data in setting links.
  return `${url.pathname}?${query}`;
}
