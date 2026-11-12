"use client";

import { useState } from "react";
import { getIdentitySyncRun, queueIdentitySync, type ApiError, type ApiFetch, type BreakGlassStatusResponse, type IdentitySyncRunResponse } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";

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
