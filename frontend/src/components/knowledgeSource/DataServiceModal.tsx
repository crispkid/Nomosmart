"use client";

import { DropdownSelect } from "@/components/DropdownSelect";
import { FeedbackConfirm } from "../FeedbackConfirm";
import { FeedbackMessage, FeedbackField } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, CalendarClock, Check, CheckCircle2, Cloud, FolderSync, KeyRound, LoaderCircle, LockKeyhole, Server, X } from "lucide-react";
import type { DataSourceConnectionOptions } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { useReadResource } from "@/lib/useReadResource";
import { ALLOWED_DOCUMENT_EXTENSIONS, HTTP_RESPONSE_EXTENSIONS, buildFriendlyCron, documentExtension, validateFiveFieldCron } from "@/lib/knowledgeImport";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import type { ServiceSource, CreatedKnowledgeDocument } from "./knowledgeSourceTypes";

type ServiceType = ServiceSource["serviceType"];
type ScheduleMode = ServiceSource["scheduleMode"];

export type DataServicePayload = {
  service_type: ServiceType;
  name: string;
  host: string;
  port: number;
  username: string;
  credential: string | null;
  credential_secret_ref?: string | null;
  bucket?: string | null;
  region?: string | null;
  remote_path: string;
  file_name: string;
  schedule_mode: ScheduleMode;
  cron_expression?: string | null;
  timezone: string;
  verify_tls: boolean;
  verify_host_key: boolean;
  url?: string | null;
  headers?: Record<string, string>;
  auth_mode?: "none" | "bearer" | "api_key_header";
  api_key_header_name?: string | null;
  timeout_seconds?: number;
  max_bytes?: number | null;
};

export function DataServiceModal({
  onClose,
  onCreate,
  onCreateDataSource,
  onTestConnection,
  onLoadConnectionOptions
}: {
  onClose: () => void;
  onCreate: (document: CreatedKnowledgeDocument) => void;
  onCreateDataSource: (payload: DataServicePayload) => Promise<CreatedKnowledgeDocument>;
  onTestConnection: (payload: DataServicePayload) => Promise<void>;
  onLoadConnectionOptions?: () => Promise<DataSourceConnectionOptions>;
}) {
  const { t, format, localize } = useI18n();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [serviceType, setServiceType] = useState<ServiceType>("S3");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [username, setUsername] = useState("");
  const [credential, setCredential] = useState("");
  const [credentialSecretRef, setCredentialSecretRef] = useState("");
  const [credentialMode, setCredentialMode] = useState<"secret_reference" | "inline">("secret_reference");
  const [url, setUrl] = useState("");
  const [authMode, setAuthMode] = useState<"none" | "bearer" | "api_key_header">("none");
  const [apiKeyHeaderName, setApiKeyHeaderName] = useState("X-API-Key");
  const [headersText, setHeadersText] = useState("");
  const [bucket, setBucket] = useState("");
  const [region, setRegion] = useState("");
  const [path, setPath] = useState("");
  const [fileName, setFileName] = useState("");
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("once");
  const [cronMode, setCronMode] = useState<"friendly" | "advanced">("friendly");
  const [frequency, setFrequency] = useState("daily");
  const [interval, setInterval] = useState("1");
  const [hour, setHour] = useState("02");
  const [minute, setMinute] = useState("00");
  const [weekday, setWeekday] = useState("1");
  const [advancedCron, setAdvancedCron] = useState("0 2 * * *");
  const [timezone, setTimezone] = useState("");
  const [verifyTls, setVerifyTls] = useState(true);
  const testGeneration = useRef(0);
  useEffect(() => () => { testGeneration.current++; }, []);
  const [testState, setTestState] = useState<"idle" | "testing" | "success" | "failed">("idle");
  const [testMessage, setTestMessage] = useState("");
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);

  const friendlyCron = buildFriendlyCron(frequency as "minutes" | "hourly" | "daily" | "weekly", Number(hour), Number(minute), Number(weekday), Number(interval));
  const cronExpression = cronMode === "advanced" ? advancedCron.trim() : friendlyCron ?? "";
  const cronValid = validateFiveFieldCron(cronExpression);
  const sourceExtensions: readonly string[] = serviceType === "HTTP_API" ? HTTP_RESPONSE_EXTENSIONS : ALLOWED_DOCUMENT_EXTENSIONS;
  const extensionValid = sourceExtensions.includes(documentExtension(fileName));
  const parsedHeaders = useMemo(() => {
    if (!headersText.trim()) return {};
    try {
      const parsed = JSON.parse(headersText);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, string> : {};
    } catch {
      return {};
    }
  }, [headersText]);
  const configuredCredential = credentialMode === "secret_reference" ? credentialSecretRef.trim() : credential;
  // OPT424-035: connection options are a read resource; the result must offer a Secret reference and a
  // valid default time zone, otherwise the step shows the options error.
  const readOptions = useCallback(async () => {
    if (!onLoadConnectionOptions) throw new Error("serviceCredentialOptionsFailed");
    const result = await onLoadConnectionOptions();
    if (!result.credential_modes.includes("secret_reference") || result.credential_modes.some(mode => !["secret_reference", "inline"].includes(mode))) throw new Error("serviceCredentialOptionsFailed");
    if (typeof result.default_timezone !== "string" || !result.default_timezone) throw new Error("serviceCredentialOptionsFailed");
    new Intl.DateTimeFormat("en", { timeZone: result.default_timezone });
    return result;
  }, [onLoadConnectionOptions]);
  const optionsRead = useReadResource<DataSourceConnectionOptions>(readOptions, "data-source-connection-options", true, {
    onData: result => {
      setTimezone(value => value || result.default_timezone);
      if (!result.credential_modes.includes(credentialMode)) { setCredentialMode("secret_reference"); setCredential(""); }
    },
  });
  const credentialOptionsState = optionsRead.status;
  const credentialModes = optionsRead.data?.credential_modes ?? [];
  const credentialModeAllowed = credentialOptionsState === "ready" && credentialModes.includes(credentialMode);
  const connectionReady = credentialModeAllowed && (serviceType === "HTTP_API" ? Boolean(url && (authMode === "none" || configuredCredential) && (authMode !== "api_key_header" || apiKeyHeaderName)) : Boolean(host && username && configuredCredential && (serviceType !== "S3" || (bucket && region)) && fileName && extensionValid));
  const sourceValid = Boolean(fileName) && extensionValid && (serviceType === "HTTP_API" || Boolean(path)) && (scheduleMode === "once" || (cronValid && timezone));
  const formValid = connectionReady && testState === "success" && sourceValid;
  const dirty = Boolean(host || username || credential || credentialSecretRef || bucket || path || fileName || url || step > 1);

  // D424-18: Esc keeps the original close rules; the hook adds focus trap and return.

  function loadCredentialOptions() { invalidateConnection(); void optionsRead.reload(); }
  function renderCredentialField() { return <>
    {credentialModes.includes("inline") ? <label><span>{t("serviceCredentialMode")}</span><DropdownSelect disabled={submitting} onChange={event => { setCredentialMode(event.target.value as "secret_reference" | "inline"); setCredential(""); setCredentialSecretRef(""); invalidateConnection(); }} value={credentialMode}><option value="secret_reference">{t("serviceCredentialSecretReference")}</option><option value="inline">{t("serviceCredentialInline")}</option></DropdownSelect></label> : null}
    <label><span>{t(credentialMode === "secret_reference" ? "serviceCredentialSecretReference" : "serviceCredentialInline")}</span><input aria-label={t(credentialMode === "secret_reference" ? "serviceCredentialSecretReference" : "serviceCredentialInline")} autoComplete="off" disabled={!credentialModeAllowed || submitting} maxLength={credentialMode === "secret_reference" ? 1000 : 8000} onChange={event => { if (credentialMode === "secret_reference") setCredentialSecretRef(event.target.value); else setCredential(event.target.value); invalidateConnection(); }} placeholder={credentialMode === "secret_reference" ? t("serviceCredentialReferencePlaceholder") : undefined} type={credentialMode === "secret_reference" ? "text" : "password"} value={credentialMode === "secret_reference" ? credentialSecretRef : credential} /><small>{t(credentialMode === "secret_reference" ? "serviceCredentialReferenceHelp" : "serviceCredentialInlineHelp")}</small></label>
  </>; }

  function requestClose() {
    if (submitting) return;
    if (dirty) setDiscardOpen(true);
    else onClose();
  }

  function dataSourcePayload(): DataServicePayload {
    return {
      service_type: serviceType,
      name: fileName || `${serviceType} data source`,
      host,
      port: Number(port),
      username,
      credential: credentialMode === "inline" && (serviceType !== "HTTP_API" || authMode !== "none") ? credential || null : null,
      credential_secret_ref: credentialMode === "secret_reference" && (serviceType !== "HTTP_API" || authMode !== "none") ? credentialSecretRef.trim() || null : null,
      bucket: serviceType === "S3" ? bucket : null,
      region: serviceType === "S3" ? region || null : null,
      remote_path: path,
      file_name: fileName,
      schedule_mode: scheduleMode,
      cron_expression: scheduleMode === "cron" ? cronExpression : null,
      timezone,
      verify_tls: serviceType === "HTTP_API" ? verifyTls : serviceType === "FTPS" || serviceType === "S3",
      verify_host_key: serviceType === "SFTP",
      url: serviceType === "HTTP_API" ? url : null,
      headers: serviceType === "HTTP_API" ? parsedHeaders : {},
      auth_mode: serviceType === "HTTP_API" ? authMode : "none",
      api_key_header_name: serviceType === "HTTP_API" && authMode === "api_key_header" ? apiKeyHeaderName : null,
      timeout_seconds: serviceType === "HTTP_API" ? 30 : undefined,
      max_bytes: null
    };
  }

  function invalidateConnection() { testGeneration.current++; setTestState("idle"); setTestMessage(""); }

  function switchService(next: ServiceType) {
    setServiceType(next);
    setPort(next === "S3" || next === "FTPS" || next === "HTTP_API" ? "443" : next === "FTP" ? "21" : "22");
    invalidateConnection();
  }

  async function testConnection() {
    if (!connectionReady || testState === "testing") return;
    const generation = ++testGeneration.current;
    setTestState("testing");
    setTestMessage("");
    try {
      await onTestConnection(dataSourcePayload());
      if (generation !== testGeneration.current) return;
      setTestState("success");
    } catch (error) {
      if (generation !== testGeneration.current) return;
      setTestMessage(operationalErrorMessage(error, t, format, "serviceConnectionFailedHelp"));
      setTestState("failed");
    }
  }

  async function submit() {
    if (!formValid || submitting) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const document = await onCreateDataSource(dataSourcePayload());
      onCreate(document);
      onClose();
    } catch (error) {
      setSubmitError(operationalErrorMessage(error, t, format, "uploadErrorFallback"));
      setSubmitting(false);
    }
  }

  const stepLabels = [t("serviceStepConnection"), t("serviceStepFileSync"), t("serviceStepReviewCreate")];
  const stepOneValid = connectionReady && testState === "success";
  const stepTwoValid = sourceValid;
  const connectionTitle = testState === "testing" ? t("serviceTestingConnection") : testState === "success" ? t("serviceConnectionSuccess") : testState === "failed" ? t("serviceConnectionFailed") : t("serviceConnectionIdle");
  const connectionHelp = testMessage ? localize(testMessage) : testState === "success" ? t("serviceConnectionSuccessHelp") : testState === "failed" ? t("serviceConnectionFailedHelp") : t("serviceConnectionIdleHelp");
  const cronPreviewHelp = frequency === "weekly" && cronMode === "friendly" ? t("serviceWeeklyPreview") : frequency === "minutes" ? format("serviceMinutesPreview", { interval }) : frequency === "hourly" ? format("serviceHourlyPreview", { interval }) : t("serviceDailyPreview");
  const footerHelp = step === 1 ? !connectionReady ? t("serviceFooterNeedConnection") : testState !== "success" ? t("serviceFooterNeedTest") : t("serviceFooterConnectionReady") : step === 2 ? !sourceValid ? t("serviceFooterNeedSource") : t("serviceFooterSourceReady") : t("serviceFooterReviewReady");

  return <Modal onEscape={() => requestClose()} onBackdropMouseDown={() => requestClose()} aria-labelledby="data-service-title" className="modal-panel source-modal data-service-modal optimized-source-modal">
      <header className="source-modal-header"><div><p className="eyebrow">{t("serviceEyebrow")}</p><h2 id="data-service-title">{t("serviceTitle")}</h2><small>{t("serviceHelp")}</small></div><button aria-label={t("serviceClose")} className="icon-button" disabled={submitting} onClick={requestClose} type="button"><X size={18} /></button></header>
      <div className="service-progress-shell"><ol aria-label={t("serviceStepsAria")} className="service-stepper">{stepLabels.map((label, index) => { const number = index + 1; const complete = number < step; const current = number === step; return <li aria-current={current ? "step" : undefined} className={complete ? "complete" : current ? "current" : "upcoming"} key={label}><span className="step-marker">{complete ? <Check size={16} /> : number}</span><div className="step-copy"><small>{format("serviceStepNumber", { number })}</small><strong>{label}</strong></div></li>; })}</ol><span aria-label={format("serviceProtocolAria", { type: serviceType, port })} className="service-protocol-pill">{serviceType} · {port}</span></div>
      <div className="source-modal-body wizard-body">
        {step === 1 ? <section className="wizard-step-panel">{credentialOptionsState === "error" ? <FeedbackMessage tone="error" title={t("serviceCredentialOptionsFailed")} actions={<button className="action-button secondary" onClick={() => void loadCredentialOptions()} type="button">{t("retry")}</button>}><p>{t("serviceCredentialOptionsRetry")}</p></FeedbackMessage> : credentialOptionsState === "loading" ? <FeedbackMessage tone="info"><p>{t("serviceCredentialOptionsLoading")}</p></FeedbackMessage> : null}<div className="wizard-section-heading"><div><strong>{t("serviceSelectTypeTitle")}</strong><small>{t("serviceSelectTypeHelp")}</small></div></div><div className="service-type-tabs service-type-cards" role="tablist">{(["S3", "FTP", "FTPS", "SFTP", "HTTP_API"] as ServiceType[]).map((type, index) => <button aria-selected={serviceType === type} className={serviceType === type ? "active" : ""} key={type} onClick={() => switchService(type)} role="tab" type="button">{type === "S3" || type === "HTTP_API" ? <Cloud size={20} /> : <Server size={20} />}<span><strong>{type}</strong><small>{type === "S3" ? t("serviceObjectStorage") : type === "HTTP_API" ? t("serviceHttpGet") : type === "FTP" ? t("serviceStandardTransfer") : t("serviceSecureTransfer")}</small></span>{serviceType === type ? <CheckCircle2 size={16} /> : null}</button>)}</div><div className="service-form-grid compact-service-form">{serviceType === "HTTP_API" ? <><label><span>{t("serviceHttpGetUrl")}</span><input onChange={(event) => { setUrl(event.target.value); invalidateConnection(); }} placeholder="https://api.example.com/document.json" value={url} /></label><label><span>{t("serviceAuthMode")}</span><DropdownSelect onChange={(event) => { setAuthMode(event.target.value as "none" | "bearer" | "api_key_header"); invalidateConnection(); }} value={authMode}><option value="none">{t("serviceAuthNone")}</option><option value="bearer">{t("serviceAuthBearer")}</option><option value="api_key_header">{t("serviceAuthApiKeyHeader")}</option></DropdownSelect></label>{authMode === "api_key_header" ? <label><span>{t("serviceApiKeyHeader")}</span><input onChange={(event) => { setApiKeyHeaderName(event.target.value); invalidateConnection(); }} value={apiKeyHeaderName} /></label> : null}{authMode !== "none" ? renderCredentialField() : null}<label><span>{t("serviceHeadersJson")}</span><textarea onChange={(event) => { setHeadersText(event.target.value); invalidateConnection(); }} placeholder={'{"Accept":"application/json"}'} value={headersText} /></label><label className="service-check-field"><input checked={verifyTls} onChange={(event) => { setVerifyTls(event.target.checked); invalidateConnection(); }} type="checkbox" /><span>{t("serviceVerifyTls")}</span></label></> : <><label><span>{serviceType === "S3" ? t("serviceS3Endpoint") : t("serviceHost")}</span><input onChange={(event) => { setHost(event.target.value); invalidateConnection(); }} placeholder={serviceType === "S3" ? "https://s3.example.com" : "files.example.com"} value={host} /></label><label><span>{t("labelPort")}</span><input inputMode="numeric" onChange={(event) => { setPort(event.target.value); invalidateConnection(); }} value={port} /></label>{serviceType === "S3" ? <><label><span>{t("labelBucket")}</span><input onChange={(event) => { setBucket(event.target.value); invalidateConnection(); }} placeholder="knowledge-source" value={bucket} /></label><label><span>{t("serviceRegionRequired")}</span><input onChange={(event) => { setRegion(event.target.value); invalidateConnection(); }} placeholder="ap-northeast-1" value={region} /></label></> : null}{serviceType === "FTPS" ? <label><span>{t("serviceFtpsSecurityMode")}</span><DropdownSelect defaultValue="explicit" onChange={invalidateConnection}><option value="explicit">Explicit TLS</option><option value="implicit">Implicit TLS</option></DropdownSelect></label> : null}<label><span>{t("labelUsernameAccessKey")}</span><input autoComplete="username" onChange={(event) => { setUsername(event.target.value); invalidateConnection(); }} value={username} /></label>{renderCredentialField()}{serviceType === "SFTP" ? <label className="service-check-field"><input defaultChecked type="checkbox" /><span>{t("serviceVerifySsh")}</span></label> : null}{serviceType === "FTPS" || serviceType === "S3" ? <label className="service-check-field"><input defaultChecked type="checkbox" /><span>{t("serviceVerifyTls")}</span></label> : null}</>}</div>{serviceType !== "HTTP_API" ? <div className="service-form-grid compact-service-form"><label><span>{t("serviceRemotePath")}</span><input onChange={event => { setPath(event.target.value); invalidateConnection(); }} value={path} /></label><label><span>{t("serviceFileName")}</span><input onChange={event => { setFileName(event.target.value); invalidateConnection(); }} value={fileName} /><small>{t("serviceConnectionFileHelp")}</small></label></div> : null}<div className={`connection-test-card ${testState}`}><span>{testState === "testing" ? <LoaderCircle className="spin" size={20} /> : testState === "success" ? <CheckCircle2 size={20} /> : testState === "failed" ? <AlertTriangle size={20} /> : <KeyRound size={20} />}</span><div><strong>{connectionTitle}</strong><small>{connectionHelp}</small></div><button className="action-button secondary" disabled={!connectionReady || testState === "testing"} onClick={testConnection} type="button">{testState === "success" || testState === "failed" ? t("serviceRetest") : t("serviceTestConnection")}</button></div></section> : null}
        {step === 2 ? <section className="wizard-step-panel">{testState !== "success" ? <FeedbackMessage tone="info" title={t("serviceSourceRetestRequired")} actions={<button className="action-button secondary" disabled={!connectionReady || testState === "testing"} onClick={() => void testConnection()} type="button">{t("serviceRetest")}</button>} /> : null}<div className="wizard-section-heading"><div><strong>{t("serviceRemoteFileTitle")}</strong><small>{t("serviceRemoteFileHelp")}</small></div><span className="service-context-pill">{serviceType} · {host}</span></div><div className="service-form-grid"><label><span>{t("serviceRemotePath")}</span><input autoFocus onChange={(event) => { setPath(event.target.value); invalidateConnection(); }} placeholder="policies/2026" value={path} /></label><label><span>{t("serviceSingleFileName")}</span><input aria-invalid={Boolean(fileName) && !extensionValid} onChange={(event) => { setFileName(event.target.value); invalidateConnection(); }} placeholder="policy.pdf" value={fileName} />{fileName && !extensionValid ? <FeedbackField>{t(serviceType === "HTTP_API" ? "serviceApiInvalidExtension" : "serviceInvalidExtension")}</FeedbackField> : null}</label></div><fieldset className="schedule-fieldset optimized-schedule"><legend><CalendarClock size={17} /> {t("serviceSyncMode")}</legend><div className="schedule-mode-options schedule-choice-cards"><label className={scheduleMode === "once" ? "active" : ""}><input checked={scheduleMode === "once"} name="schedule" onChange={() => setScheduleMode("once")} type="radio" /><span><strong>{t("serviceOnce")}</strong><small>{t("serviceOnceHelp")}</small></span></label><label className={scheduleMode === "cron" ? "active" : ""}><input checked={scheduleMode === "cron"} name="schedule" onChange={() => setScheduleMode("cron")} type="radio" /><span><strong>{t("serviceCron")}</strong><small>{t("serviceCronHelp")}</small></span></label></div>{scheduleMode === "cron" ? <div className="cron-builder"><div className="cron-mode-tabs"><button className={cronMode === "friendly" ? "active" : ""} onClick={() => setCronMode("friendly")} type="button">{t("serviceFriendly")}</button><button className={cronMode === "advanced" ? "active" : ""} onClick={() => setCronMode("advanced")} type="button">{t("serviceAdvancedCron")}</button></div>{cronMode === "friendly" ? <div className="friendly-cron-fields"><label><span>{t("serviceFrequency")}</span><DropdownSelect onChange={(event) => setFrequency(event.target.value)} value={frequency}><option value="minutes">{t("serviceEveryMinutes")}</option><option value="hourly">{t("serviceEveryHours")}</option><option value="daily">{t("serviceDaily")}</option><option value="weekly">{t("serviceWeekly")}</option></DropdownSelect></label>{frequency === "minutes" || frequency === "hourly" ? <label><span>{t("serviceInterval")}</span><input max={frequency === "minutes" ? 59 : 23} min="1" onChange={(event) => setInterval(event.target.value)} type="number" value={interval} /></label> : null}{frequency === "weekly" ? <label><span>{t("serviceWeekday")}</span><DropdownSelect onChange={(event) => setWeekday(event.target.value)} value={weekday}><option value="1">{t("serviceMonday")}</option><option value="2">{t("serviceTuesday")}</option><option value="3">{t("serviceWednesday")}</option><option value="4">{t("serviceThursday")}</option><option value="5">{t("serviceFriday")}</option><option value="6">{t("serviceSaturday")}</option><option value="0">{t("serviceSunday")}</option></DropdownSelect></label> : null}{frequency !== "minutes" ? <label><span>{frequency === "hourly" ? t("serviceHourlyMinute") : t("serviceTime")}</span>{frequency === "hourly" ? <input max="59" min="0" onChange={(event) => setMinute(event.target.value)} type="number" value={minute} /> : <span className="time-inputs"><input aria-label={t("serviceHourAria")} max="23" min="0" onChange={(event) => setHour(event.target.value)} type="number" value={hour} /><b>:</b><input aria-label={t("serviceMinuteAria")} max="59" min="0" onChange={(event) => setMinute(event.target.value)} type="number" value={minute} /></span>}</label> : null}</div> : <label className="advanced-cron-field"><span>{t("serviceFiveFieldCron")}</span><input aria-invalid={!cronValid} onChange={(event) => setAdvancedCron(event.target.value)} value={advancedCron} />{!cronValid ? <FeedbackField>{t("serviceInvalidCron")}</FeedbackField> : null}</label>}<label className="timezone-field"><span>{t("serviceTimezone")}</span><DropdownSelect onChange={(event) => setTimezone(event.target.value)} value={timezone}><option>Asia/Taipei</option><option>Asia/Tokyo</option><option>America/New_York</option><option>Europe/London</option></DropdownSelect></label><div className="cron-preview"><FolderSync size={17} /><span><strong>{cronExpression || t("serviceCronIncomplete")}</strong><small>{cronPreviewHelp} · {timezone} · {t("serviceNextRun")}</small></span></div></div> : null}</fieldset></section> : null}
        {step === 3 ? <section className="wizard-step-panel"><div className="wizard-section-heading"><div><strong>{t("serviceReviewTitle")}</strong><small>{t("serviceReviewHelp")}</small></div><span className="review-safe-badge"><LockKeyhole size={14} /> {t("serviceSecretHidden")}</span></div><div className="service-review-grid"><div><small>{t("serviceConnection")}</small><strong>{serviceType}</strong><span>{host}:{port}</span>{serviceType === "S3" ? <span>{bucket}{region ? ` · ${region}` : ""}</span> : null}</div><div><small>{t("serviceSourceFile")}</small><strong>{fileName}</strong><span>{path}</span><span>{t("serviceSingleFileSync")}</span></div><div><small>{t("serviceSchedule")}</small><strong>{scheduleMode === "once" ? t("serviceOnce") : t("serviceCron")}</strong><span>{scheduleMode === "cron" ? cronExpression : t("serviceRunOnceNow")}</span><span>{timezone}{scheduleMode === "cron" ? ` · ${t("serviceNextRun")}` : ""}</span></div></div><div className="service-create-explainer"><FolderSync size={22} /><div><strong>{t("serviceCreateExplainerTitle")}</strong><ol><li>{t("serviceCreateStepDocument")}</li><li>{t("serviceCreateStepSync")}</li><li>{t("serviceCreateStepExtraction")}</li></ol></div></div>{submitError ? <div className="upload-result-summary upload-error-summary" role="alert"><AlertTriangle size={20} /><div><strong>{t("uploadIncomplete")}</strong><small>{localize(submitError)}</small></div></div> : null}</section> : null}
      </div>
      <footer className="source-modal-footer wizard-footer"><small>{footerHelp}</small><div><button className="action-button secondary" disabled={submitting} onClick={requestClose} type="button">{t("cancel")}</button>{step > 1 ? <button className="action-button secondary" disabled={submitting} onClick={() => setStep((step - 1) as 1 | 2)} type="button"><ArrowLeft size={16} /> {t("previousStep")}</button> : null}{step < 3 ? <button className="action-button" disabled={step === 1 ? !stepOneValid : !stepTwoValid} onClick={() => setStep((step + 1) as 2 | 3)} type="button">{t("nextStep")} <ArrowRight size={16} /></button> : <button className="action-button" disabled={!formValid || submitting} onClick={submit} type="button">{submitting ? <LoaderCircle className="spin" size={16} /> : <FolderSync size={16} />} {t("serviceCreate")}</button>}</div></footer>
      {discardOpen ? <FeedbackConfirm title={t("serviceDiscardTitle")} cancelLabel={t("continueEditing")} confirmLabel={t("discardAndClose")} onCancel={() => setDiscardOpen(false)} onConfirm={onClose}>{t("serviceDiscardHelp")}</FeedbackConfirm> : null}
    </Modal>;
}
