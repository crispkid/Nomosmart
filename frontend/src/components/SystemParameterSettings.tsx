"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RotateCcw, Save, RefreshCw } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { useReadResource } from "@/lib/useReadResource";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";
import { getSystemParameters, patchSystemParameters, type ApiError, type SystemParameterApiValues, type SystemParametersPayload } from "@/lib/api";
import { useOperationGuard } from "./useOperationGuard";
import { FeedbackMessage } from "./FeedbackMessage";
import { SettingsCard, SettingsFieldRow } from "./SettingsCard";

type Key = keyof SystemParameterApiValues;
type Field = { key: Key; label: TranslationKey; help: TranslationKey; max?: number; min?: number; zero?: boolean };
const fields: Record<"general" | "documents", { panel: string; title: TranslationKey; fields: Field[] }[]> = {
  general: [
    { panel: "time", title: "settingsTime", fields: [{ key: "default_timezone", label: "systemDefaultTimezoneLabel", help: "settingsTimezoneHelp" }] },
    { panel: "drafts", title: "settingsDrafts", fields: [{ key: "session_expired_form_draft_ttl_minutes", label: "systemSessionDraftTtlLabel", help: "systemSessionDraftTtlHelp", min: 5, max: 120, zero: true }] }
  ],
  documents: [
    { panel: "upload", title: "settingsUpload", fields: [{ key: "max_upload_size_mb", label: "systemUploadLimitLabel", help: "settingsUploadHelp", min: 1, max: 10240 }] },
    { panel: "retention", title: "settingsRetention", fields: [{ key: "staging_index_ttl_days", label: "systemStagingTtlLabel", help: "settingsRetentionHelp", min: 1, max: 3650 }] },
    { panel: "ocr", title: "settingsOCR", fields: [
      { key: "ocr_request_max_output_tokens", label: "ocrRequestTokenSettingLabel", help: "ocrRequestTokenSettingHelp", min: 1, max: 2147483647 },
      { key: "ocr_document_max_tokens", label: "ocrDocumentTokenSettingLabel", help: "ocrDocumentTokenSettingHelp", min: 1, max: 2147483647 }
    ] }
  ]
};

export default function SystemParameterSettings({ section, onDirtyChange }: {
  section: "general" | "documents"; onDirtyChange: (dirty: boolean) => void;
}) {
  const { apiFetch, can, currentUser, operationGuards } = useAuth();
  const { t, format, locale } = useI18n();
  const groups = fields[section];
  const keys = groups.flatMap(group => group.fields.map(field => field.key));
  const [draft, setDraft] = useState<Partial<Record<Key, string>>>({});
  const [baseline, setBaseline] = useState<Partial<Record<Key, string>>>({});
  const [errors, setErrors] = useState<Partial<Record<Key, TranslationKey>>>({});
  const [notice, setNotice] = useState<TranslationKey | null>(null);
  const [saveError, setError] = useState<ApiError | Error | null>(null);
  const [comparison, setComparison] = useState<SystemParametersPayload | null>(null);
  const [checking, setChecking] = useState(false);
  const restoredDraft = useRef<Partial<Record<Key, string>> | null>(null);
  const { guard, state, blocked } = useOperationGuard(`system.parameters:${currentUser?.user_id}:${section}`, operationGuards);
  const dirty = keys.some(key => draft[key] !== baseline[key]);
  const editable = can("Menu", "SystemManagement", "edit");
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  // OPT424-035: the editor is keyed by section; it reloads only on an explicit reload. Earlier values
  // stay visible while reloading or after a failed reload.
  const readParameters = useCallback((signal: AbortSignal) => getSystemParameters(apiFetch, signal), [apiFetch]);
  const parametersRead = useReadResource<SystemParametersPayload>(readParameters, section, true, {
    keepData: true,
    onData: value => {
      const values = Object.fromEntries(keys.map(key => [key, String(value[key])]));
      setDraft({ ...values, ...restoredDraft.current }); restoredDraft.current = null; setBaseline(values); setError(null);
    },
  });
  const data = parametersRead.data;
  const loading = parametersRead.status === "loading";
  const error = saveError ?? (parametersRead.status === "error" ? parametersRead.error as ApiError | Error : null);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty || blocked) { event.preventDefault(); event.returnValue = ""; } };
    const restore = (event: Event) => {
      const detail = (event as CustomEvent<{ formKey: string; payload: Record<string, unknown> }>).detail;
      if (detail?.formKey !== "system.parameters") return;
      const aliases: Record<Key, string> = { max_upload_size_mb: "uploadLimitMb", default_timezone: "timezone", staging_index_ttl_days: "stagingTtlDays", session_expired_form_draft_ttl_minutes: "sessionDraftTtlMinutes", ocr_request_max_output_tokens: "ocrRequestOutputTokens", ocr_document_max_tokens: "ocrDocumentOutputTokens" };
      const restored = Object.fromEntries(keys.filter(key => ["string", "number"].includes(typeof detail.payload[aliases[key]])).map(key => [key, String(detail.payload[aliases[key]])]));
      restoredDraft.current = restored;
      setDraft(previous => ({ ...previous, ...restored }));
    };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("nomosmart:restore-session-draft", restore);
    return () => { window.removeEventListener("beforeunload", beforeUnload); window.removeEventListener("nomosmart:restore-session-draft", restore); };
  });
  async function save() {
    if (!data || !editable || blocked) return;
    const problems: Partial<Record<Key, TranslationKey>> = {};
    const values: Record<string, string | number> = {};
    for (const field of groups.flatMap(group => group.fields)) {
      const value = draft[field.key] ?? "";
      if (field.key === "default_timezone") {
        try { if (!value) throw new Error(); new Intl.DateTimeFormat("en", { timeZone: value }); }
        catch { problems[field.key] = "settingsInvalidTimezone"; }
        values[field.key] = value;
      } else {
        const number = Number(value);
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(number) || number > field.max! || number < field.min! && !(field.zero && number === 0)) problems[field.key] = "settingsInvalidInteger";
        if (field.key === "max_upload_size_mb" && number > data.deployment_max_upload_size_mb) problems[field.key] = "settingsCapacityError";
        values[field.key] = number;
      }
    }
    if (section === "documents" && Number(values.ocr_document_max_tokens) < Number(values.ocr_request_max_output_tokens)) problems.ocr_document_max_tokens = "ocrTokenDocumentTooSmall";
    setErrors(problems);
    if (Object.keys(problems).length) return;
    const changes = Object.fromEntries(keys.filter(key => draft[key] !== baseline[key]).map(key => [key, values[key]]));
    if (!Object.keys(changes).length) return;
    const token = guard.begin();
    if (token === null) return;
    setError(null); setNotice(null);
    try {
      const response = await patchSystemParameters(apiFetch, section, data.section_revisions[section], changes);
      if (!guard.current(token)) return;
      guard.accepted(token);
      const saved = Object.fromEntries(keys.map(key => [key, String(response.values[key])]));
      parametersRead.update(previous => ({ ...previous, ...response.values, parameter_metadata: { ...previous.parameter_metadata, ...response.parameter_metadata }, section_revisions: { ...previous.section_revisions, [section]: response.revision } }));
      setDraft(saved); setBaseline(saved); setNotice("systemParametersSaved"); guard.complete(token);
    } catch (caught) {
      guard.failed(token, caught); setError(caught as ApiError | Error);
      const details = (caught as ApiError).details;
      if (details && typeof details === "object") {
        const reasons = details as Record<string, unknown>;
        setErrors(Object.fromEntries(keys.filter(key => key in reasons).map(key => [key, reasons[key] === "deployment_capacity_exceeded" ? "settingsCapacityError" : key === "default_timezone" ? "settingsInvalidTimezone" : reasons[key] === "document_budget_below_request" ? "ocrTokenDocumentTooSmall" : "settingsInvalidInteger"])));
      }
    }
  }
  async function compareCurrent() {
    if (checking) return;
    setChecking(true);
    try { setComparison(await getSystemParameters(apiFetch)); }
    catch (caught) { setError(caught as ApiError | Error); }
    finally { setChecking(false); }
  }
  const unknown = ["unknown", "read_failed", "accepted"].includes(state.phase);
  return <div className="settings-parameter-editor" data-session-draft-key="system.parameters">
    {loading ? <FeedbackMessage tone="info">{t("loadingData")}</FeedbackMessage> : null}
    {error || unknown ? <FeedbackMessage tone={unknown ? "warning" : "error"} title={t(unknown ? "feedbackResultUnknown" : (error as ApiError)?.code === "system_parameters_conflict" ? "settingsConflict" : "systemReadFailedTitle")} actions={<><button className="action-button secondary" type="button" disabled={checking} onClick={() => void compareCurrent()}><RefreshCw size={16} />{t("settingsCompare")}</button>{!unknown ? <button className="action-button secondary" type="button" disabled={dirty} onClick={() => { setError(null); void parametersRead.reload(); }}><RefreshCw size={16} />{t("retry")}</button> : null}</>}>{t(unknown ? "settingsUnknownHelp" : (error as ApiError)?.code === "system_parameters_conflict" ? "settingsConflictHelp" : "settingsSaveError")}</FeedbackMessage> : null}
    {comparison ? <div className="system-table-wrap"><table className="system-table"><thead><tr><th>{t("systemParameters")}</th><th>{t("systemUnsavedChanges")}</th><th>{t("settingsCurrentValue")}</th></tr></thead><tbody>{groups.flatMap(group => group.fields).map(field => <tr key={field.key}><th>{t(field.label)}</th><td>{draft[field.key]}</td><td>{String(comparison[field.key])}</td></tr>)}</tbody></table><button className="action-button secondary" disabled={unknown} type="button" onClick={() => { const values = Object.fromEntries(keys.map(key => [key, String(comparison[key])])); parametersRead.update(() => comparison); setDraft(values); setBaseline(values); setComparison(null); setErrors({}); setError(null); }}>{t("settingsUseCurrent")}</button></div> : null}
    {groups.map(group => <SettingsCard key={group.panel} panel={group.panel} title={t(group.title)}>
      {group.fields.map(field => {
        const id = `setting-${field.key}`, metadata = data?.parameter_metadata[field.key];
        const aliases: Record<string, string> = { max_upload_size_mb: "uploadLimitMb", default_timezone: "timezone", staging_index_ttl_days: "stagingTtlDays", session_expired_form_draft_ttl_minutes: "sessionDraftTtlMinutes", ocr_request_max_output_tokens: "ocrRequestOutputTokens", ocr_document_max_tokens: "ocrDocumentOutputTokens" };
        return <SettingsFieldRow key={field.key} htmlFor={id} label={t(field.label)} help={t(field.help)} extra={field.key === "max_upload_size_mb" && data ? <small>{format("settingsPlatformLimit", { limit: data.deployment_max_upload_size_mb })}</small> : undefined}><input id={id} disabled={!editable || !data || blocked} aria-invalid={Boolean(errors[field.key])} aria-describedby={`${id}-help${errors[field.key] ? ` ${id}-error` : ""}`} type={field.max ? "number" : "text"} min={field.zero ? 0 : field.min} max={field.key === "max_upload_size_mb" && data ? Math.min(field.max!, data.deployment_max_upload_size_mb) : field.max} value={draft[field.key] ?? ""} data-session-draft-raw data-session-draft-field={aliases[field.key]} onChange={event => { setDraft(previous => ({ ...previous, [field.key]: event.target.value })); setErrors(previous => ({ ...previous, [field.key]: undefined })); setNotice(null); }} />{errors[field.key] ? <small className="settings-field-error" id={`${id}-error`}>{t(errors[field.key]!)}</small> : null}<small className="settings-field-meta">{metadata?.updated_at ? new Date(metadata.updated_at).toLocaleString(locale) : t("systemReadCountUnknown")}{metadata?.updated_by ? ` · ${metadata.updated_by}` : ""}</small></SettingsFieldRow>;
      })}
    </SettingsCard>)}
    <footer className="settings-save-bar"><span aria-live="polite">{t(notice || (dirty ? "systemUnsavedChanges" : "systemSaved"))}</span><div><button className="action-button secondary" type="button" disabled={!editable || !data || blocked} onClick={() => { setDraft(Object.fromEntries(keys.map(key => [key, String(data!.parameter_defaults[key])]))); setErrors({}); setNotice("systemParametersDefaultsRestored"); }}><RotateCcw size={16} />{t("systemRestoreDefaults")}</button><button className="action-button secondary" disabled={!dirty || blocked} type="button" onClick={() => { setDraft(baseline); setErrors({}); setError(null); setNotice(null); }}>{t("cancel")}</button><button className="action-button" type="button" disabled={!editable || !data || !dirty || blocked} onClick={() => void save()}><Save size={16} />{t(state.phase === "submitting" ? "loadingData" : "systemSaveParameters")}</button></div></footer>
  </div>;
}
