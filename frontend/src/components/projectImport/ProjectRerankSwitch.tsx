"use client";

import { useEffect, useState } from "react";
import { ListFilter } from "lucide-react";
import { getProjectRetrievalSettings, updateProjectRetrievalSettings, type ApiFetch, type ProjectRetrievalSettings } from "@/lib/api";
import type { TranslationKey } from "@/lib/i18nClient";

/**
 * CHG-486 RERANK486-004: the project's rerank switch. Every member sees its state; only Project Owners change it
 * here (administrators use System Management). It is disabled while the system switch is off.
 */
export function ProjectRerankSwitch({ apiFetch, projectId, t }: { apiFetch: ApiFetch; projectId: string; t: (key: TranslationKey) => string }) {
  const [settings, setSettings] = useState<ProjectRetrievalSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    getProjectRetrievalSettings(apiFetch, projectId, controller.signal).then(setSettings).catch(() => setSettings(null));
    return () => controller.abort();
  }, [apiFetch, projectId]);
  if (!settings) return null;
  const disabled = saving || !settings.can_edit || (!settings.rerank_available && !settings.rerank_enabled);
  const hint: TranslationKey = !settings.rerank_available ? "projectRerankSystemOff" : settings.can_edit ? "projectRerankHelp" : "projectRerankOwnerOnly";
  async function toggle(next: boolean) {
    setSaving(true); setFailed(false);
    try { setSettings(await updateProjectRetrievalSettings(apiFetch, projectId, next)); }
    catch { setFailed(true); }
    finally { setSaving(false); }
  }
  return <label className="settings-toggle project-rerank-switch" title={t(hint)}>
    <ListFilter size={16} aria-hidden="true" />
    <input type="checkbox" checked={settings.rerank_enabled} disabled={disabled} aria-describedby="project-rerank-hint" onChange={event => void toggle(event.target.checked)} />
    <span>{t(settings.rerank_enabled ? "projectRerankOn" : "projectRerankOff")}</span>
    <small id="project-rerank-hint" className="sr-only">{t(hint)}</small>
    {failed ? <small className="settings-field-error" role="alert">{t("projectRerankSaveFailed")}</small> : null}
  </label>;
}
