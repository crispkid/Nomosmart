"use client";

import { DropdownSelect } from "@/components/DropdownSelect";

import { useCallback, useId, useRef, useState, useSyncExternalStore } from "react";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { FeedbackMessage } from "./FeedbackMessage";
import { listApprovalFilterOptions, type ApprovalTab } from "@/lib/api";
import { approvalListFilters, emptyApprovalFilters, type ApprovalFilterOption, type ApprovalFilterValues } from "@/lib/approvalFilters";
import { useCursorList } from "@/lib/useCursorList";
import { useI18n } from "@/lib/i18nClient";
import { operationalErrorMessage } from "@/lib/operationalMessages";

const subscribeTimezone = () => () => {};
const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverTimezone = () => "";

function FilterCandidate({ kind, tab, projectId, value, onChange }: {
  kind: "project" | "submitter"; tab: ApprovalTab; projectId?: string;
  value: ApprovalFilterOption | null; onChange: (value: ApprovalFilterOption | null) => void;
}) {
  const { apiFetch, operationGuards, authReady } = useAuth();
  const { t, format } = useI18n();
  const id = useId();
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const read = useCallback((cursor?: string | null, signal?: AbortSignal) => listApprovalFilterOptions(apiFetch, { kind, tab, project_id: projectId, q: query || undefined }, cursor, signal), [apiFetch, kind, tab, projectId, query]);
  const list = useCursorList(read, operationGuards, authReady);
  const label = t(kind === "project" ? "approvalProjectLabel" : "approvalSubmitter");
  const selectedLoaded = value && list.items.some(item => item.id === value.id);
  return <fieldset className="approval-filter-candidate">
    <legend>{label}</legend>
    <div className="approval-option-search">
      <label className="sr-only" htmlFor={`${id}-query`}>{format("approvalFilterFindOption", { field: label })}</label>
      <input id={`${id}-query`} maxLength={100} onChange={event => setInput(event.target.value)} onKeyDown={event => {
        if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
        event.preventDefault(); if (input.trim() === query) void list.reload(); else setQuery(input.trim());
      }} placeholder={t("approvalFilterOptionPlaceholder")} type="search" value={input} />
      <button aria-label={format("approvalFilterFindOption", { field: label })} className="action-button secondary" onClick={() => { if (input.trim() === query) void list.reload(); else setQuery(input.trim()); }} type="button"><Search aria-hidden="true" size={16} /></button>
    </div>
    <label className="sr-only" htmlFor={`${id}-select`}>{label}</label>
    <DropdownSelect aria-describedby={`${id}-status`} disabled={list.loading && !list.ready} id={`${id}-select`} onChange={event => onChange(list.items.find(item => item.id === event.target.value) ?? (event.target.value === value?.id ? value : null))} value={value?.id ?? ""}>
      <option value="">{t("approvalFilterAll")}</option>
      {value && !selectedLoaded ? <option value={value.id}>{value.label}</option> : null}
      {list.items.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </DropdownSelect>
    <span aria-live="polite" className="form-helper" id={`${id}-status`}>{list.loading ? t("uiReadLoading") : list.error ? operationalErrorMessage(list.error, t, format, "apiGenericError") : !list.items.length ? t("approvalFilterNoOptions") : format("uiLoadedCount", { count: list.items.length })}</span>
    {list.error ? <button className="text-link" onClick={() => { void list.reload(); }} type="button">{t("uiReadRetry")}</button> : list.hasMore ? <button className="text-link" disabled={list.loading} onClick={() => { void list.loadMore(); }} type="button">{t("uiLoadMore")}</button> : null}
  </fieldset>;
}

export function ApprovalFilters({ tab, applied, onApply }: { tab: ApprovalTab; applied: ApprovalFilterValues; onApply: (values: ApprovalFilterValues) => void }) {
  const { operationGuards } = useAuth();
  const zone = useSyncExternalStore(subscribeTimezone, browserTimezone, serverTimezone);
  const { t, format } = useI18n();
  const [draft, setDraft] = useState({ scope: operationGuards, values: applied });
  const values = draft.scope === operationGuards ? draft.values : emptyApprovalFilters;
  const [invalidDate, setInvalidDate] = useState(false);
  const dateRef = useRef<HTMLInputElement>(null);
  const id = useId();
  const change = (patch: Partial<ApprovalFilterValues>) => { setDraft({ scope: operationGuards, values: { ...values, ...patch } }); setInvalidDate(false); };
  const resultOptions = tab === "mine" ? ["pending_manager_review", "pending_owner_review", "approved", "rejected", "cancelled"] : ["approved", "rejected", "cancelled"];
  const resultLabel = (status: string) => t(status === "approved" ? "approved" : status === "rejected" ? "rejected" : status === "pending_manager_review" ? "statusPendingManagerReview" : status === "pending_owner_review" ? "statusPendingOwnerReview" : "approvalFilterCancelled");
  return <form aria-label={t("approvalFilterTitle")} className="approval-filters" onSubmit={event => {
    event.preventDefault();
    try { approvalListFilters(values, tab); setInvalidDate(false); onApply(values); }
    catch { setInvalidDate(true); dateRef.current?.focus(); }
  }}>
    <div className="approval-filter-grid">
      <FilterCandidate key={`project-${tab}`} kind="project" onChange={project => change({ project, submitter: null })} tab={tab} value={values.project} />
      <label className="approval-filter-field"><span>{t("approvalFilterDocument")}</span><input maxLength={100} onChange={event => change({ query: event.target.value })} placeholder={t("approvalFilterDocumentPlaceholder")} type="search" value={values.query} /></label>
      <label className="approval-filter-field"><span>{t("approvalFilterStage")}</span><DropdownSelect onChange={event => change({ stage: event.target.value })} value={values.stage}><option value="">{t("approvalFilterAll")}</option><option value="manager_review">{t("approvalStageManagerReview")}</option><option value="owner_review">{t("approvalStageOwnerReview")}</option></DropdownSelect></label>
      <label className="approval-filter-field"><span>{t("approvalFilterResult")}</span><DropdownSelect disabled={tab === "pending" || tab === "rejected"} onChange={event => change({ result: event.target.value })} value={tab === "pending" ? "pending" : tab === "rejected" ? "rejected" : values.result}>
        {tab === "pending" ? <option value="pending">{t("approvalFilterPending")}</option> : <><option value="">{t("approvalFilterAll")}</option>{resultOptions.map(value => <option key={value} value={value}>{resultLabel(value)}</option>)}</>}
      </DropdownSelect></label>
      <label className="approval-filter-field"><span>{t("approvalFilterDateFrom")}</span><input aria-describedby={invalidDate ? `${id}-error` : undefined} aria-invalid={invalidDate || undefined} onChange={event => change({ from: event.target.value })} ref={dateRef} type="date" value={values.from} /></label>
      <label className="approval-filter-field"><span>{t("approvalFilterDateTo")}</span><input aria-describedby={invalidDate ? `${id}-error` : undefined} aria-invalid={invalidDate || undefined} onChange={event => change({ to: event.target.value })} type="date" value={values.to} /></label>
    </div>
    <p className="form-helper">{format("approvalFilterTimezone", { zone: zone || t("approvalFilterLocalTimezone") })}</p>
    <details className="approval-filter-advanced"><summary><SlidersHorizontal aria-hidden="true" size={16} />{t("approvalFilterAdvanced")}</summary><div className="approval-filter-grid">
      {tab !== "mine" ? <FilterCandidate key={`submitter-${tab}-${values.project?.id ?? "all"}`} kind="submitter" onChange={submitter => change({ submitter })} projectId={values.project?.id} tab={tab} value={values.submitter} /> : <p className="form-helper">{t("approvalFilterMineSubmitter")}</p>}
      <label className="approval-filter-field"><span>{t("approvalFilterPriority")}</span><input maxLength={32} onChange={event => change({ priority: event.target.value })} placeholder={t("approvalFilterPriorityPlaceholder")} value={values.priority} /></label>
      <label className="approval-filter-field"><span>{t("approvalFilterSource")}</span><input maxLength={50} onChange={event => change({ source: event.target.value })} placeholder={t("approvalFilterSourcePlaceholder")} value={values.source} /></label>
    </div></details>
    {invalidDate ? <div id={`${id}-error`}><FeedbackMessage>{t("approvalFilterDateInvalid")}</FeedbackMessage></div> : null}
    <div className="approval-filter-actions"><button className="action-button" type="submit"><Search aria-hidden="true" size={16} />{t("approvalFilterApply")}</button><button className="action-button secondary" onClick={() => { setDraft({ scope: operationGuards, values: emptyApprovalFilters }); setInvalidDate(false); onApply(emptyApprovalFilters); }} type="button"><X aria-hidden="true" size={16} />{t("approvalFilterClear")}</button><span className="form-helper">{t("approvalFilterScope")}</span></div>
  </form>;
}
