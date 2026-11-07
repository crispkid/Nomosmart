"use client";

import { DropdownSelect } from "@/components/DropdownSelect";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { KeyRound, LockKeyhole, Play, RefreshCw, Save, Search, ShieldCheck } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { FeedbackMessage } from "./FeedbackMessage";
import { apiBaseUrl } from "@/lib/oidc";
import { apiJson, type ApiError, type UserSummary } from "@/lib/api";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

type Directory = { source_id: string; name: string; schema_type: "ldap" | "ad"; endpoints: string[]; start_tls: boolean; ca_reference: string; users_dn: string; groups_dn: string; bind_dn: string; user_filter: string; group_filter: string; login_attribute: string; object_id_attribute: string; group_id_attribute: string; group_member_attribute: "member" | "uniqueMember" | "memberUid"; employee_attribute: string; enabled_attribute: string; disabled_value: string; page_size: number; maximum_entries: number };
type Oidc = { issuer: string; client_id: string; client_auth_method: "none" | "client_secret_basic" | "client_secret_post"; scopes: string; mapping_claim: string; mapping_attribute: "object_id" | "employee_id"; employee_id_immutable: boolean; discovery_url: string; token_url: string; jwks_url: string; ca_reference: string };
type Configuration = { auth_contract_revision: 2; auth_mode: "oidc" | "ldap"; display_name: string; directory: Directory; oidc: Oidc | null; sync_enabled: boolean; sync_scope: "people" | "groups" | "people_and_groups"; sync_schedule: string; timezone: string };
type Snapshot = { configuration: Configuration; revision: number; editable: boolean; unlock_expires_at: string | null; last_sync_success_at?: string | null; secrets: Record<string, { configured: boolean }> };
type Candidate = { candidate_id: string; state: string; candidate_login_required: boolean };
type Run = { id: string; status: string; phase: string; queued_at: string; error_code: string | null;
  provider_results?: { provider_id: string; provider_name: string; status: string }[] };
const runStatusKeys: Record<string, TranslationKey> = { succeeded: "protocolRunSucceeded", failed: "protocolRunFailed", queued: "protocolRunQueued", running: "protocolRunRunning" };
const runPhaseKeys: Record<string, TranslationKey> = { queued: "identitySyncPhaseQueued", snapshot_fetch: "protocolDirectorySnapshot", reconciliation: "identitySyncPhaseReconciliation", completed: "identitySyncPhaseCompleted", failed: "identitySyncPhaseFailed" };
function waitForRunPoll(signal: AbortSignal) {
  signal.throwIfAborted();
  return new Promise<void>((resolve, reject) => {
    const aborted = () => { window.clearTimeout(timer); reject(new DOMException("Sync status tracking stopped", "AbortError")); };
    const timer = window.setTimeout(() => { signal.removeEventListener("abort", aborted); resolve(); }, 1500);
    signal.addEventListener("abort", aborted, { once: true });
  });
}
const pendingKey = "nomosmart-auth-candidate-id";
const defaultOidc: Oidc = { issuer: "", client_id: "", client_auth_method: "none", scopes: "openid profile email", mapping_claim: "directory_id", mapping_attribute: "object_id", employee_id_immutable: false, discovery_url: "", token_url: "", jwks_url: "", ca_reference: "" };

export default function ProtocolIdentityPanel({ canEdit }: { canEdit: boolean }) {
  const { apiFetch, currentUser } = useAuth();
  const { t } = useI18n();
  const [saved, setSaved] = useState<Snapshot | null>(null);
  const [cfg, setCfg] = useState<Configuration | null>(null);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [people, setPeople] = useState<UserSummary[]>([]);
  const [selectedPerson, setSelectedPerson] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<TranslationKey | null>(null);
  const [credentialPurpose, setCredentialPurpose] = useState<"current" | "candidate" | null>(null);
  const [remaining, setRemaining] = useState(0);
  const configurationForm = useRef<HTMLFormElement | null>(null);
  const completed = useRef(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const syncWatch = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    const data = await apiJson<Snapshot>(apiFetch, "/system/identity-settings");
    setSaved(data); setCfg(data.configuration);
    configurationForm.current?.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach(input => { input.value = ""; });
    configurationForm.current?.querySelectorAll<HTMLSelectElement>("select[data-secret-operation]").forEach(select => { select.value = "keep"; });
    const history = await apiJson<{ items: Run[] }>(apiFetch, "/identity-sync/runs?limit=10");
    setRuns(history.items);
  }, [apiFetch]);
  const failure = useCallback((e: unknown) => {
    const code = (e as ApiError).code;
    const messages: Record<string, TranslationKey> = { identity_settings_locked: "protocolLocked", identity_revision_conflict: "protocolRevisionChanged", identity_candidate_invalid: "protocolCandidateExpired", identity_binding_conflict: "protocolBindingConflict", identity_binding_invalid: "protocolBindingInvalid", invalid_credentials: "protocolFreshAuthFailed", fresh_authentication_failed: "protocolFreshAuthFailed", validation_error: "protocolInvalidSettings", directory_bind_failed: "protocolDirectoryFailed", directory_unavailable: "protocolDirectoryFailed", auth_endpoint_denied: "protocolEndpointDenied", identity_provider_unavailable: "protocolOIDCFailed", identity_sync_worker_unavailable: "protocolWorkerUnavailable", identity_sync_already_running: "protocolSyncAlreadyRunning" };
    setError(t(messages[code] || "protocolSettingsFailed"));
  }, [t]);
  useEffect(() => {
    if (leaveTimer.current) { clearTimeout(leaveTimer.current); leaveTimer.current = null; }
    const initial = window.setTimeout(() => { void load().catch(failure); }, 0);
    if (!completed.current && new URL(window.location.href).searchParams.get("reauth") === "success") {
      completed.current = true;
      const pending = new URL(window.location.href).searchParams.get("reauth_purpose") === "candidate" ? sessionStorage.getItem(pendingKey) : null;
      const work = pending ? apiJson<Candidate>(apiFetch, `/system/identity-settings/candidates/${encodeURIComponent(pending)}`).then(setCandidate) : apiJson(apiFetch, "/system/identity-settings/reauth/complete", { method: "POST" });
      void work.then(load).catch(failure);
      const url = new URL(window.location.href); url.searchParams.delete("reauth"); url.searchParams.delete("reauth_purpose"); window.history.replaceState(null, "", url.pathname + url.search);
    }
    return () => { window.clearTimeout(initial); syncWatch.current?.abort(); leaveTimer.current = setTimeout(() => { void apiFetch(`${apiBaseUrl()}/system/identity-settings/lock`, { method: "POST", keepalive: true }).catch(() => undefined); }, 0); };
  }, [apiFetch, failure, load]);
  useEffect(() => {
    const update = () => setRemaining(saved?.unlock_expires_at ? Math.max(0, Math.ceil((Date.parse(saved.unlock_expires_at) - Date.now()) / 1000)) : 0);
    const timer = window.setInterval(update, 1000); const initial = window.setTimeout(update, 0);
    return () => { window.clearInterval(timer); window.clearTimeout(initial); };
  }, [saved]);
  const unlocked = Boolean(saved?.editable && remaining > 0 && canEdit);
  function changed(next: Configuration) { setCfg(next); setCandidate(null); sessionStorage.removeItem(pendingKey); }
  async function reauthenticate(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault(); if (busy || !saved) return;
    const form = event?.currentTarget;
    const fields = form ? new FormData(form) : null;
    setBusy(true); setError(null);
    try {
      const result = await apiJson<{ authorization_url?: string; candidate_verified?: boolean }>(apiFetch, "/system/identity-settings/reauth/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ purpose: credentialPurpose || "current", candidate_id: candidate?.candidate_id, username: fields?.get("username") || undefined, password: fields?.get("password") || undefined }) });
      form?.reset();
      if (result.authorization_url) { window.location.assign(result.authorization_url); return; }
      if (result.candidate_verified && candidate) setCandidate({ ...candidate, state: "validated_candidate", candidate_login_required: false });
      setCredentialPurpose(null); await load();
    } catch (e) { failure(e); } finally { setBusy(false); }
  }
  async function validate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!cfg || !saved || busy) return;
    const form = event.currentTarget, fields = new FormData(form);
    const secrets: Record<string, { operation: string; value?: string }> = {};
    for (const purpose of ["ldap_bind_password", "oidc_client_secret"]) {
      const operation = String(fields.get(`${purpose}_operation`) || "keep");
      secrets[purpose] = { operation, ...(operation === "replace" ? { value: String(fields.get(purpose) || "") } : {}) };
    }
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await apiJson<Candidate>(apiFetch, "/system/identity-settings/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ configuration: { ...cfg, directory: { ...cfg.directory, endpoints: cfg.directory.endpoints.map(endpoint => endpoint.trim()).filter(Boolean) } }, expected_revision: saved.revision, secrets }) });
      form.querySelectorAll<HTMLInputElement>('input[type="password"]').forEach(input => { input.value = ""; });
      setCandidate(result); sessionStorage.setItem(pendingKey, result.candidate_id); setNotice("protocolCandidateReady");
    } catch (e) { failure(e); } finally { setBusy(false); }
  }
  async function activate() {
    if (!candidate || !saved || busy) return;
    setBusy(true); setError(null);
    try {
      const result = await apiJson<{ reauthentication_required: boolean }>(apiFetch, "/system/identity-settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_id: candidate.candidate_id, expected_revision: saved.revision }) });
      setCandidate(null);sessionStorage.removeItem(pendingKey);
      if (result.reauthentication_required) { window.location.replace("/login?notice=session_expired"); return; }
      setNotice("protocolSettingsSaved"); await load();
    } catch (e) { failure(e); } finally { setBusy(false); }
  }
  async function sync() {
    if (busy || syncWatch.current) return;
    const watch = new AbortController(); syncWatch.current = watch;
    setBusy(true);setError(null);
    try {
      let run = await apiJson<Run>(apiFetch, "/identity-sync/run", { method: "POST", signal: watch.signal });
      setNotice("protocolSyncQueued");
      const queued = run;
      setRuns(previous => [queued, ...previous.filter(item => item.id !== queued.id)].slice(0, 10));
      while (run.status === "queued" || run.status === "running") {
        await waitForRunPoll(watch.signal);
        run = await apiJson<Run>(apiFetch, `/identity-sync/runs/${encodeURIComponent(run.id)}`, { signal: watch.signal });
        const current = run;
        setRuns(previous => [current, ...previous.filter(item => item.id !== current.id)].slice(0, 10));
      }
      await load();
      if (run.status === "failed") { setNotice(null);setError(t("protocolRunFailed")); }
      else setNotice("protocolRunSucceeded");
    } catch (e) { if (!watch.signal.aborted) failure(e); }
    finally { if (syncWatch.current === watch) { syncWatch.current = null; setBusy(false); } }
  }
  async function searchPeople(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError(null);
    try {
      const query = String(new FormData(event.currentTarget).get("person_search") || "");
      const result = await apiJson<UserSummary[]>(apiFetch, `/users?q=${encodeURIComponent(query)}&limit=20&is_active=true`);
      setPeople(result.filter(person => person.directory_source_id === saved?.configuration.directory.source_id));setSelectedPerson("");
    } catch (e) { failure(e); } finally { setBusy(false); }
  }
  async function bindPerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!saved?.configuration.oidc || busy) return;
    const person = people.find(item => item.id === selectedPerson);
    if (!person?.directory_object_id) return;
    const subject = String(new FormData(event.currentTarget).get("oidc_subject") || "");
    setBusy(true);setError(null);
    try {
      await apiJson(apiFetch, "/system/identity-settings/identity-bindings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: saved.configuration.directory.source_id, issuer: saved.configuration.oidc.issuer, subject, user_id: person.id, directory_object_id: person.directory_object_id, expected_revision: saved.revision }) });
      setNotice("protocolBindingSaved");
    } catch (e) { failure(e); } finally { setBusy(false); }
  }
  if (!cfg || !saved) return <FeedbackMessage tone={error ? "error" : "info"}>{error || t("authCheckingSession")}</FeedbackMessage>;
  const textField = (key: string, label: TranslationKey, value: string, onChange: (value: string) => void, required = true) => <label className="identity-field" key={key}><span>{t(label)}</span><input value={value} onChange={event => onChange(event.target.value)} required={required} autoComplete="off" /></label>;
  const oidc = cfg.oidc || defaultOidc;
  const credentialMode = currentUser?.mode === "emergency" ? "emergency" : credentialPurpose === "candidate" ? cfg.auth_mode : saved.configuration.auth_mode;
  const directCredentials = credentialMode !== "oidc";
  const credentialExplanation: TranslationKey = credentialMode === "ldap" ? "protocolDirectoryReauthHelp" : credentialMode === "emergency" ? "protocolEmergencyReauthHelp" : "identityReauthExplanation";
  return <section>
    <header className="section-header"><div><h2>{t("protocolSettingsTitle")}</h2><p>{t("protocolSettingsHelp")}</p></div>{canEdit ? unlocked ? <button className="action-button secondary" disabled={busy} type="button" onClick={() => { void apiJson(apiFetch, "/system/identity-settings/lock", { method: "POST" }).then(load).catch(failure); }}><LockKeyhole size={16} />{t("identityCancelAndLock")} ({remaining} {t("protocolSeconds")})</button> : <button className="action-button" disabled={busy} type="button" onClick={() => setCredentialPurpose("current")}><ShieldCheck size={16} />{t("identityReauthToEdit")}</button> : null}</header>
    {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}{notice ? <FeedbackMessage tone="success">{t(notice)}</FeedbackMessage> : null}
    {credentialPurpose ? <form className="identity-settings-section" onSubmit={reauthenticate}><h3>{t("identityConfirmIdentity")}</h3>{credentialPurpose === "candidate" ? <p>{t("protocolCandidateLoginHelp")}</p> : null}<p>{t(credentialExplanation)}</p>{directCredentials ? <><label>{t("protocolUsername")}<input name="username" autoComplete="username" required={currentUser?.mode !== "emergency"} /></label><label>{t("protocolPassword")}<input name="password" type="password" autoComplete="current-password" required /></label></> : null}<button className="action-button" disabled={busy} type="submit">{t("protocolContinue")}</button><button className="action-button secondary" type="button" disabled={busy} onClick={() => setCredentialPurpose(null)}>{t("identityCancel")}</button></form> : null}
    <form ref={configurationForm} onSubmit={validate}><fieldset className="identity-settings-section" disabled={!unlocked || busy}><legend><KeyRound size={18} /> {t("protocolSignInMethod")}</legend><div className="identity-form-grid">
      <label className="identity-field"><span>{t("protocolSignInMethod")}</span><DropdownSelect value={cfg.auth_mode} onChange={event => changed({ ...cfg, auth_mode: event.target.value as Configuration["auth_mode"], oidc: event.target.value === "oidc" ? oidc : cfg.oidc })}><option value="oidc">{t("protocolOIDC")}</option><option value="ldap">{t("protocolLDAPAD")}</option></DropdownSelect></label>
      {textField("display", "protocolDisplayName", cfg.display_name, display_name => changed({ ...cfg, display_name }))}
    </div>
    {cfg.auth_mode === "oidc" ? <><h3>{t("protocolOIDC")}</h3><div className="identity-form-grid">{([ ["issuer", "labelIssuer"], ["client_id", "protocolClientId"], ["scopes", "protocolScopes"], ["mapping_claim", "protocolMappingClaim"], ["ca_reference", "protocolCAReference"] ] as [keyof Oidc, TranslationKey][]).map(([key, label]) => textField(key, label, String(oidc[key]), value => changed({ ...cfg, oidc: { ...oidc, [key]: value } }), key !== "ca_reference"))}
      <label>{t("protocolClientAuth")}<DropdownSelect value={oidc.client_auth_method} onChange={event => changed({ ...cfg, oidc: { ...oidc, client_auth_method: event.target.value as Oidc["client_auth_method"] } })}><option value="none">{t("protocolPublicClient")}</option><option value="client_secret_basic">{t("protocolSecretBasic")}</option><option value="client_secret_post">{t("protocolSecretPost")}</option></DropdownSelect></label>
      <label>{t("protocolDirectoryIdentifier")}<DropdownSelect value={oidc.mapping_attribute} onChange={event => changed({ ...cfg, oidc: { ...oidc, mapping_attribute: event.target.value as Oidc["mapping_attribute"] } })}><option value="object_id">{t("protocolObjectId")}</option><option value="employee_id">{t("protocolEmployeeId")}</option></DropdownSelect></label>{oidc.mapping_attribute === "employee_id" ? <label><input type="checkbox" checked={oidc.employee_id_immutable} onChange={event => changed({ ...cfg, oidc: { ...oidc, employee_id_immutable: event.target.checked } })} />{t("protocolImmutableEmployeeId")}</label> : null}
    </div><details><summary>{t("protocolAdvancedTransport")}</summary><p>{t("protocolAdvancedTransportHelp")}</p><div className="identity-form-grid">{([ ["discovery_url", "protocolDiscoveryURL"], ["token_url", "protocolTokenURL"], ["jwks_url", "protocolJWKSURL"] ] as [keyof Oidc, TranslationKey][]).map(([key, label]) => textField(key, label, String(oidc[key]), value => changed({ ...cfg, oidc: { ...oidc, [key]: value } }), false))}</div></details></> : null}</fieldset>
    <fieldset className="identity-settings-section" disabled={!unlocked || busy}><legend>{t("protocolDirectoryTitle")}</legend><p>{t("protocolDirectoryHelp")}</p><div className="identity-form-grid"><label>{t("protocolDirectoryType")}<DropdownSelect disabled title={t("protocolSchemaFixedHelp")} value={cfg.directory.schema_type} onChange={event => { const ad = event.target.value === "ad";changed({ ...cfg, directory: { ...cfg.directory, schema_type: ad ? "ad" : "ldap", login_attribute: ad ? "sAMAccountName" : "uid", object_id_attribute: ad ? "objectGUID" : "entryUUID", group_id_attribute: ad ? "objectGUID" : "entryUUID", user_filter: ad ? "(&(objectClass=user)(objectCategory=person))" : "(objectClass=inetOrgPerson)", group_filter: ad ? "(objectClass=group)" : "(objectClass=groupOfNames)" } }); }}><option value="ldap">{t("protocolLDAP")}</option><option value="ad">{t("protocolAD")}</option></DropdownSelect></label>
      {([ ["name", "protocolDirectoryName"], ["users_dn", "protocolUsersDN"], ["groups_dn", "protocolGroupsDN"], ["bind_dn", "protocolBindDN"], ["ca_reference", "protocolCAReference"], ["user_filter", "protocolUserFilter"], ["group_filter", "protocolGroupFilter"], ["login_attribute", "protocolLoginAttribute"], ["employee_attribute", "protocolEmployeeAttribute"], ["enabled_attribute", "protocolEnabledAttribute"] ] as [keyof Directory, TranslationKey][]).map(([key, label]) => textField(key, label, String(cfg.directory[key]), value => changed({ ...cfg, directory: { ...cfg.directory, [key]: value } }), !["ca_reference", "enabled_attribute"].includes(key)))}
      <label>{t("protocolEndpoints")}<textarea required value={cfg.directory.endpoints.join("\n")} onChange={event => changed({ ...cfg, directory: { ...cfg.directory, endpoints: event.target.value.split("\n") } })} /></label><label><input type="checkbox" checked={cfg.directory.start_tls} onChange={event => changed({ ...cfg, directory: { ...cfg.directory, start_tls: event.target.checked } })} />{t("protocolStartTLS")}</label>
    </div><details><summary>{t("protocolDirectoryAdvanced")}</summary><p>{t("protocolSchemaFixedHelp")}</p><div className="identity-form-grid"><label>{t("protocolMemberAttribute")}<DropdownSelect value={cfg.directory.group_member_attribute} onChange={event => changed({ ...cfg, directory: { ...cfg.directory, group_member_attribute: event.target.value as Directory["group_member_attribute"] } })}>{["member", "uniqueMember", "memberUid"].map(value => <option key={value} value={value}>{value}</option>)}</DropdownSelect></label>{textField("disabled_value", "protocolDisabledValue", cfg.directory.disabled_value, value => changed({ ...cfg, directory: { ...cfg.directory, disabled_value: value } }))}<label>{t("protocolPageSize")}<input type="number" min={1} max={1000} required value={cfg.directory.page_size} onChange={event => changed({ ...cfg, directory: { ...cfg.directory, page_size: Number(event.target.value) } })} /></label><label>{t("protocolMaximumEntries")}<input type="number" min={1} max={1000000} required value={cfg.directory.maximum_entries} onChange={event => changed({ ...cfg, directory: { ...cfg.directory, maximum_entries: Number(event.target.value) } })} /></label></div></details></fieldset>
    <fieldset className="identity-settings-section" disabled={!unlocked || busy}><legend>{t("protocolCredentials")}</legend><p>{t("protocolCredentialsHelp")}</p><div className="identity-form-grid">{["ldap_bind_password", ...(cfg.auth_mode === "oidc" ? ["oidc_client_secret"] : [])].map(purpose => <label key={purpose}><span>{t(purpose === "ldap_bind_password" ? "protocolBindPassword" : "protocolClientSecret")} — {t(saved.secrets[purpose]?.configured ? "protocolConfigured" : "protocolNotConfigured")}</span><DropdownSelect data-secret-operation name={`${purpose}_operation`} defaultValue="keep"><option value="keep">{t("protocolKeepSecret")}</option><option value="replace">{t("protocolReplaceSecret")}</option><option value="clear">{t("protocolClearSecret")}</option></DropdownSelect><input name={purpose} type="password" autoComplete="new-password" aria-label={t(purpose === "ldap_bind_password" ? "protocolBindPassword" : "protocolClientSecret")} /></label>)}</div></fieldset>
    <fieldset className="identity-settings-section" disabled={!unlocked || busy}><legend>{t("protocolScheduleTitle")}</legend><div className="identity-form-grid"><label><input type="checkbox" checked={cfg.sync_enabled} onChange={event => changed({ ...cfg, sync_enabled: event.target.checked })} />{t("protocolDailySync")}</label><label>{t("protocolDailyTime")}<input type="time" required value={`${cfg.sync_schedule.split(" ")[1].padStart(2, "0")}:${cfg.sync_schedule.split(" ")[0].padStart(2, "0")}`} onChange={event => { const [hour, minute] = event.target.value.split(":");if (hour && minute) changed({ ...cfg, sync_schedule: `${Number(minute)} ${Number(hour)} * * *` }); }} /></label>{textField("timezone", "protocolTimezone", cfg.timezone, timezone => changed({ ...cfg, timezone }))}<label>{t("protocolSyncScope")}<DropdownSelect value={cfg.sync_scope} onChange={event => changed({ ...cfg, sync_scope: event.target.value as Configuration["sync_scope"] })}><option value="people_and_groups">{t("protocolPeopleAndGroups")}</option><option value="people">{t("protocolPeopleOnly")}</option><option value="groups">{t("protocolGroupsOnly")}</option></DropdownSelect></label></div><p>{t("protocolDailyDelayHelp")}</p></fieldset>
    <button className="action-button" disabled={!unlocked || busy} type="submit"><ShieldCheck size={16} />{t("protocolValidateCandidate")}</button></form>
    {candidate ? <div className="identity-settings-section"><p>{t("protocolCandidateReady")}</p>{candidate.candidate_login_required && candidate.state !== "validated_candidate" ? <button className="action-button" disabled={!unlocked || busy} onClick={() => setCredentialPurpose("candidate")} type="button">{t("protocolCandidateSignIn")}</button> : <button className="action-button" disabled={!unlocked || busy} onClick={() => { void activate(); }} type="button"><Save size={16} />{t("protocolActivate")}</button>}</div> : null}
    {saved.configuration.oidc ? <section className="identity-settings-section"><h3>{t("protocolManualBinding")}</h3><p>{t("protocolManualBindingHelp")}</p><form onSubmit={searchPeople}><fieldset disabled={!unlocked || busy}><label>{t("protocolSearchPerson")}<input name="person_search" required /></label><button className="action-button secondary" type="submit"><Search size={16} />{t("protocolSearch")}</button></fieldset></form><form onSubmit={bindPerson}><fieldset disabled={!unlocked || busy}><label>{t("protocolSelectPerson")}<DropdownSelect value={selectedPerson} required onChange={event => setSelectedPerson(event.target.value)}><option value="">{t("protocolSelectPerson")}</option>{people.map(person => <option key={person.id} value={person.id}>{person.display_name} ({person.employee_id})</option>)}</DropdownSelect></label><label>{t("protocolOIDCSubject")}<input name="oidc_subject" required maxLength={255} autoComplete="off" /></label><button className="action-button secondary" disabled={!selectedPerson} type="submit">{t("protocolBindPerson")}</button></fieldset></form></section> : null}
    <section className="identity-settings-section"><h3>{t("protocolSyncHistory")}</h3><button className="action-button secondary" disabled={!canEdit || busy} onClick={() => { void sync(); }} type="button"><Play size={16} />{t("protocolSyncNow")}</button><p>{t("protocolLastSuccessfulSync")}: {saved.last_sync_success_at ? new Date(saved.last_sync_success_at).toLocaleString() : t("protocolNoSuccessfulSync")}</p><button className="action-button secondary" disabled={busy} onClick={() => { void load().catch(failure); }} type="button"><RefreshCw size={16} />{t("refresh")}</button><table><thead><tr><th>{t("protocolRunTime")}</th><th>{t("protocolRunStatus")}</th></tr></thead><tbody>{runs.map(run => <tr data-sync-run-id={run.id} key={run.id}><td>{new Date(run.queued_at).toLocaleString()}</td><td><span>{run.error_code ? t("protocolRunFailed") : t(runStatusKeys[run.status] || "protocolRunUnknown")}</span><small>{t(runPhaseKeys[run.phase] || "identitySyncPhaseUnknown")}</small>{run.provider_results?.length ? <ul className="identity-provider-results">{run.provider_results.map(provider => <li key={provider.provider_id}>{provider.provider_name}: {t(runStatusKeys[provider.status] || "protocolRunUnknown")}</li>)}</ul> : null}</td></tr>)}</tbody></table></section>
  </section>;
}
