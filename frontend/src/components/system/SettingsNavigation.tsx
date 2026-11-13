"use client";

import type { RefObject } from "react";
import { Activity, Bot, ChevronRight, KeyRound, Layers3, Search, ShieldCheck, SlidersHorizontal, UsersRound, X } from "lucide-react";
import type { TranslationKey } from "@/lib/i18nClient";
import { settingsSections, type SettingsPosition } from "@/lib/systemRouteState";

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

type SettingsNavigationProps = {
  activeSection: SettingsPosition["section"];
  leaveOpen: boolean;
  narrow: boolean;
  navOpen: boolean;
  navigateSettings: (next: SettingsPosition) => void;
  navigationRef: RefObject<HTMLElement | null>;
  setNavOpen: (open: boolean) => void;
  setSettingsSearch: (value: string) => void;
  settingsSearch: string;
  t: (key: TranslationKey) => string;
};

/** Settings category list and panel search for the system workspace (OPT424-038). */
export function SettingsNavigation({ activeSection, leaveOpen, narrow, navOpen, navigateSettings, navigationRef, setNavOpen, setSettingsSearch, settingsSearch, t }: SettingsNavigationProps) {
  const searchText = (section: (typeof settingsSections)[number], panel: string) => [section.labelKey, settingsPanelLabels[panel], settingsPanelHelp[panel] || settingsPanelLabels[panel], ...(settingsSearchFields[panel] || [])].map(key => t(key)).join(" ").toLocaleLowerCase();
  return <>
    {narrow && navOpen ? <div className="settings-nav-backdrop" onClick={() => setNavOpen(false)} /> : null}
    <aside id="settings-navigation" ref={navigationRef} inert={leaveOpen} role={narrow && navOpen && !leaveOpen ? "dialog" : undefined} aria-modal={narrow && navOpen && !leaveOpen ? true : undefined} aria-label={t("settingsCategories")} className={`settings-navigation${navOpen ? " is-open" : ""}`}>
      <div className="settings-nav-heading"><strong>{t("settingsCategories")}</strong><button className="icon-button settings-menu-close" aria-label={t("close")} onClick={() => setNavOpen(false)} type="button"><X size={18} /></button></div>
      <label className="settings-search"><Search size={16} /><input type="search" value={settingsSearch} aria-label={t("settingsSearch")} placeholder={t("settingsSearch")} onChange={event => setSettingsSearch(event.target.value)} /></label>
      <nav aria-label={t("settingsCategories")}>{settingsSections.map((section, index) => {
        const Icon = [UsersRound, ShieldCheck, Bot, Layers3, KeyRound, SlidersHorizontal, Activity][index];
        return <button type="button" key={section.id} aria-current={activeSection === section.id ? "page" : undefined} onClick={() => navigateSettings({ section: section.id, panel: section.panels[0] })}><Icon size={18} /><span>{t(section.labelKey)}</span><ChevronRight size={15} /></button>;
      })}</nav>
      {settingsSearch.trim() ? <div className="settings-search-results" aria-live="polite">{settingsSections.flatMap(section => section.panels.map(panel => ({ section, panel, label: t(settingsPanelLabels[panel]) }))).filter(item => searchText(item.section, item.panel).includes(settingsSearch.trim().toLocaleLowerCase())).map(item => <button type="button" key={item.panel} onClick={() => { navigateSettings({ section: item.section.id, panel: item.panel }); }}><span>{t(item.section.labelKey)}</span><strong>{item.label}</strong></button>)}{!settingsSections.some(section => section.panels.some(panel => searchText(section, panel).includes(settingsSearch.trim().toLocaleLowerCase()))) ? <p>{t("settingsSearchEmpty")}</p> : null}</div> : null}
    </aside>
  </>;
}
