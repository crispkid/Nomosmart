"use client";

import { useState } from "react";
import { getIdentitySyncRun, queueIdentitySync, type ApiError, type ApiFetch, type BreakGlassStatusResponse, type IdentitySyncRunResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";
import ProtocolIdentityPanel from "../ProtocolIdentityPanel";
import { StateBadge } from "./SystemUi";
import type { WorkspaceViewDeps } from "./viewDeps";

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

/** Workspace dependencies shared with the identity section. */
export type IdentityDeps = {
  apiFetch: ApiFetch;
  t: (key: TranslationKey) => string;
  errorMessage: (error: ApiError | Error | null) => string;
  refreshRolesAndMappings: (current?: () => boolean) => Promise<void>;
  reloadSystemSection: (section: string, current?: () => boolean) => Promise<boolean>;
  sectionReady: (section: string) => boolean;
};

function identitySyncErrorKey(errorCode: string | null): TranslationKey {
  if (errorCode === "identity_sync_queue_timeout") return "identitySyncQueueTimeout";
  if (errorCode === "identity_sync_heartbeat_timeout" || errorCode === "identity_sync_run_budget_insufficient") return "identitySyncRunTimeout";
  return "identitySyncFailed";
}

export type IdentityState = ReturnType<typeof useIdentityState>;

/** Directory sync and emergency access state (split from SystemManagementWorkspace, OPT424-038). */
export function useIdentityState() {
  const [identityDirty, setIdentityDirty] = useState(false);
  const [syncRuns, setSyncRuns] = useState<IdentitySyncRunResponse[]>([]);
  const [identitySyncing, setIdentitySyncing] = useState(false);
  const [breakGlassStatus, setBreakGlassStatus] = useState<BreakGlassStatusResponse | null>(null);
  const [identityMessage, setIdentityMessage] = useState("");
  return { identityDirty, setIdentityDirty, syncRuns, setSyncRuns, identitySyncing, setIdentitySyncing, breakGlassStatus, setBreakGlassStatus, identityMessage, setIdentityMessage };
}

/** Directory sync and emergency access actions, created each render once workspace dependencies exist. */
export function createIdentityActions(state: IdentityState, deps: IdentityDeps) {
  const { identityDirty, setIdentityDirty, syncRuns, setSyncRuns, identitySyncing, setIdentitySyncing, breakGlassStatus, setBreakGlassStatus, identityMessage, setIdentityMessage } = state;
  const { sectionReady, t } = deps;

  const localizedBreakGlassStatus = (status?: BreakGlassStatusResponse["status"]) => {
    if (!sectionReady("breakGlass")) return t("systemReadCountUnknown");
    if (status === "configured_disabled") return t("identityBreakGlassConfiguredDisabled");
    if (status === "attention_required") return t("identityNeedsAttention");
    if (status === "unavailable") return t("systemOpUnavailable");
    return t("systemNotConfigured");
  };

  async function refreshIdentityData() {
    const { refreshRolesAndMappings, reloadSystemSection } = deps;
    const success = await reloadSystemSection("users");
    await refreshRolesAndMappings();
    if (!success) throw new Error("System read could not be confirmed");
  }

  async function runIdentitySync() {
    const { apiFetch, errorMessage, t } = deps;
    if (identitySyncing || syncRuns.some((run) => run.status === "queued" || run.status === "running")) return;
    setIdentitySyncing(true);
    setIdentityMessage(t("identitySyncInProgress"));
    try {
      let run = await queueIdentitySync(apiFetch);
      const queued = run;
      setSyncRuns((current) => [queued, ...current.filter((item) => item.id !== queued.id)]);
      while (run.status === "queued" || run.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        run = await getIdentitySyncRun(apiFetch, run.id);
        const latest = run;
        setSyncRuns((current) => [latest, ...current.filter((item) => item.id !== latest.id)]);
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

  return { localizedBreakGlassStatus, refreshIdentityData, runIdentitySync };
}

export type IdentityActions = ReturnType<typeof createIdentityActions>;

/** Identity view: JSX moved verbatim from SystemManagementWorkspace (OPT424-038). */
export function createIdentityView(state: IdentityState, actions: IdentityActions, deps: Pick<WorkspaceViewDeps, "canEditSystemManagement" | "format" | "locale" | "renderSectionReadNotice" | "systemReadScope" | "t">) {
  const { setIdentityDirty, breakGlassStatus } = state;
  const { localizedBreakGlassStatus } = actions;

  function renderIdentityPanel() {
    const { canEditSystemManagement, format, locale, renderSectionReadNotice, systemReadScope, t } = deps;
    return (
      <>
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
    </>
    );
  }

  return { renderIdentityPanel };
}
