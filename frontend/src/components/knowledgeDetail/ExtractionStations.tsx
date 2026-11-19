"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, FileText, Link2, Loader2, RotateCcw, Trash2, X } from "lucide-react";
import { FeedbackMessage } from "@/components/FeedbackMessage";
import { Modal } from "@/components/Modal";
import {
  createChunkReference, deleteChunkReference, listChunkReferences, listProjectDocuments, updateChunkReference,
  type ApiFetch, type ChunkReferenceItem, type DocumentSummary, type KnowledgeDetailResponse, type StationReuseSummary,
} from "@/lib/api";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import type { TranslationKey } from "@/lib/i18n";
import type { Format, Translate } from "./knowledgeDetailModel";

/** CHG-442 STAGE442-001: station numbers and their names. */
export const STATIONS = [1, 2, 3, 4] as const;
export type StationNumber = (typeof STATIONS)[number];
const STATION_NAME: Record<StationNumber, TranslationKey> = { 1: "stationName1", 2: "stationName2", 3: "stationName3", 4: "stationName4" };
const STATION_STEPS: Record<StationNumber, string[]> = {
  1: ["upload_received", "parse_document", "ocr_extract", "generate_markdown"],
  2: ["split_paragraphs", "chunk_knowledge"],
  3: ["auto_tag", "extract_references"],
  4: ["build_embeddings", "build_staging_index", "build_graph_preview", "prepare_submission"],
};

export function stationName(station: number, t: Translate) {
  return t(STATION_NAME[station as StationNumber] ?? "stationName1");
}

export function usesStations(detail: KnowledgeDetailResponse | null): boolean {
  return Boolean(detail?.stations?.length);
}

/** The station a person works on now: the paused one, else 4 when extraction finished, else the running one. */
export function activeStation(detail: KnowledgeDetailResponse | null): StationNumber | null {
  if (!usesStations(detail) || !detail) return null;
  if (detail.current_station) return detail.current_station as StationNumber;
  const steps = detail.pipeline?.steps ?? [];
  for (const station of STATIONS) {
    if (STATION_STEPS[station].some(name => steps.find(step => step.step_name === name)?.status !== "completed")) return station;
  }
  return 4;
}

type StationPhase = "done" | "waiting" | "running" | "pending";

function stationPhase(detail: KnowledgeDetailResponse, station: StationNumber, active: StationNumber | null): StationPhase {
  const row = detail.stations?.find(item => item.station === station);
  if (row?.status === "confirmed" || (station === 4 && row?.status === "ready")) return "done";
  if (row?.status === "ready" && detail.current_station === station) return "waiting";
  if (active === station) return "running";
  return "pending";
}

const PHASE_LABEL: Record<StationPhase, TranslationKey> = { done: "stationStatusDone", waiting: "stationStatusReady", running: "stationStatusRunning", pending: "stationStatusPending" };

/** STAGE442-003: four-station progress bar; reached stations can be viewed, later ones stay closed. */
export function StationStepper({ detail, viewStation, onView, t }: {
  detail: KnowledgeDetailResponse; viewStation: StationNumber; onView: (station: StationNumber) => void; t: Translate;
}) {
  const active = activeStation(detail);
  return (
    <ol aria-label={t("stationStepperLabel")} className="service-stepper station-stepper">
      {STATIONS.map(station => {
        const phase = stationPhase(detail, station, active);
        const reachable = phase !== "pending";
        const className = [phase === "done" ? "complete" : "", station === viewStation ? "current" : "", reachable ? "" : "unreached"].filter(Boolean).join(" ");
        return (
          <li className={className} key={station}>
            <button aria-current={station === viewStation ? "step" : undefined} disabled={!reachable} onClick={() => onView(station)} type="button">
              <span>{phase === "done" ? <Check size={16} aria-hidden="true" /> : phase === "running" ? <Loader2 className="spin" size={16} aria-hidden="true" /> : station}</span>
              <div><strong>{stationName(station, t)}</strong><small>{t(PHASE_LABEL[phase])}</small></div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** Action row for the viewed station: confirm the waiting one, or go back to a finished one (STAGE442-002/009). */
export function StationActions({ detail, viewStation, canEdit, busy, error, onConfirm, onReopen, t, format }: {
  detail: KnowledgeDetailResponse; viewStation: StationNumber; canEdit: boolean; busy: boolean; error: string | null;
  onConfirm: (station: StationNumber) => void; onReopen: (station: StationNumber) => void; t: Translate; format: Format;
}) {
  const active = activeStation(detail);
  const phase = stationPhase(detail, viewStation, active);
  const reopenable = canEdit && viewStation < 4 && phase === "done" && ["awaiting_confirmation", "submission_ready"].includes(detail.version.status);
  return (
    <div className="station-actions" role="group" aria-label={stationName(viewStation, t)}>
      <div className="station-actions-text">
        <strong>{format("stationHeading", { station: viewStation, name: stationName(viewStation, t) })}</strong>
        <small>{t(phase === "waiting" ? (viewStation === 3 ? "stationWaitingHelpLast" : "stationWaitingHelp") : phase === "done" ? (viewStation === 4 ? "stationDoneHelp" : "stationReadonlyNote") : phase === "running" ? "stationRunningHelp" : "stationNotReached")}</small>
        <StationReuseNote reuse={detail.station_reuse} station={viewStation} format={format} />
      </div>
      {phase === "waiting" && canEdit && viewStation < 4 ? (
        <button className="action-button" disabled={busy} onClick={() => onConfirm(viewStation)} type="button">
          {busy ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />} {t(viewStation === 3 ? "stationConfirmLast" : "stationConfirmNext")}
        </button>
      ) : null}
      {reopenable ? (
        <button className="action-button secondary" disabled={busy} onClick={() => onReopen(viewStation)} type="button">
          <RotateCcw size={16} /> {t("stationReopen")}
        </button>
      ) : null}
      {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}
    </div>
  );
}

/** STAGE442-009: kept vs redone counts after a station was done again. */
export function StationReuseNote({ reuse, station, format }: { reuse?: StationReuseSummary | null; station: StationNumber; format: Format }) {
  if (!reuse) return null;
  const lines: string[] = [];
  if (station >= 2 && reuse.reused_chunks !== undefined) {
    lines.push(format("stationReuseChunks", { kept: reuse.reused_chunks ?? 0, redone: reuse.new_chunks ?? 0 }));
    if (reuse.manual_kept || reuse.manual_dropped) lines.push(format("stationReuseManual", { kept: reuse.manual_kept ?? 0, dropped: reuse.manual_dropped ?? 0 }));
  }
  if (station >= 3 && reuse.reused_tag_chunks !== undefined) lines.push(format("stationReuseTags", { kept: reuse.reused_tag_chunks ?? 0, redone: reuse.tagged_chunks ?? 0 }));
  if (station === 4 && reuse.reused_vectors !== undefined) lines.push(format("stationReuseVectors", { kept: reuse.reused_vectors ?? 0, redone: reuse.new_vectors ?? 0 }));
  return lines.length ? <small className="station-reuse-note" role="status">{lines.join("；")}</small> : null;
}

/** STAGE442-009: confirmation before going back; lists the stations that will be done again. */
export function StationReopenDialog({ station, chunkCount, busy, error, onCancel, onConfirm, t, format }: {
  station: StationNumber; chunkCount: number; busy: boolean; error: string | null; onCancel: () => void; onConfirm: () => void; t: Translate; format: Format;
}) {
  const redo = STATIONS.filter(item => item > station).map(item => format("stationNumbered", { station: item, name: stationName(item, t) })).join("、");
  const close = () => { if (!busy) onCancel(); };
  return (
    <Modal aria-labelledby="station-reopen-title" className="modal-panel modal-compact" onBackdropMouseDown={close} onEscape={close}>
      <div className="modal-header">
        <div><h2 id="station-reopen-title">{format("stationReopenTitle", { station, name: stationName(station, t) })}</h2></div>
        <button aria-label={t("cancel")} className="icon-button" disabled={busy} onClick={close} type="button"><X size={18} /></button>
      </div>
      <p>{format("stationReopenBody", { stations: redo })}</p>
      <p className="field-note">{format("stationReopenChunks", { count: chunkCount })}</p>
      {station === 1 ? <p className="field-note">{t("stationReopenStation1Note")}</p> : null}
      {error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}
      <div className="modal-actions">
        <button className="action-button secondary" disabled={busy} onClick={close} type="button">{t("cancel")}</button>
        <button className="action-button" disabled={busy} onClick={onConfirm} type="button">{busy ? <Loader2 className="spin" size={16} /> : <RotateCcw size={16} />} {t("stationReopenConfirm")}</button>
      </div>
    </Modal>
  );
}

/** STAGE442-010: a rejected (or published) version starts a revision at station 1. */
export function StationRevisionBanner({ busy, error, onCreate, t }: { busy: boolean; error: string | null; onCreate: () => void; t: Translate }) {
  return (
    <div className="review-banner warning station-revision-banner" role="status">
      <AlertTriangle size={20} />
      <div><strong>{t("stationRevisionTitle")}</strong><p>{t("stationRevisionBody")}</p>{error ? <FeedbackMessage tone="error">{error}</FeedbackMessage> : null}</div>
      <button className="action-button" disabled={busy} onClick={onCreate} type="button">{busy ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />} {t("stationRevisionAction")}</button>
    </div>
  );
}

type ChecklistItem = { key: string; label: string; offset: number; excerpt: string };

/** Code-point offsets of tables and images in the Markdown, for the station 1 check list. */
export function contentChecklist(markdown: string) {
  const tables: ChecklistItem[] = [];
  const images: ChecklistItem[] = [];
  let offset = 0;
  let inTable = false;
  for (const line of markdown.split("\n")) {
    const trimmed = line.trim();
    const isTableLine = trimmed.startsWith("|") && trimmed.endsWith("|");
    if (isTableLine && !inTable) tables.push({ key: `t${offset}`, label: "", offset, excerpt: trimmed.slice(0, 60) });
    inTable = isTableLine;
    for (const match of line.matchAll(/!\[([^\]]*)\]\([^)]*\)|<img\b[^>]*>/g)) {
      images.push({ key: `i${offset + (match.index ?? 0)}`, label: match[1] ?? "", offset: offset + (match.index ?? 0), excerpt: match[0].slice(0, 60) });
    }
    offset += line.length + 1;
  }
  return { characters: Array.from(markdown.replace(/\s/g, "")).length, tables, images };
}

/** STAGE442-005: content check list (pages, characters, tables, images, low-confidence OCR); items locate the text. */
export function ContentChecklist({ detail, onLocate, t, format }: { detail: KnowledgeDetailResponse; onLocate: (excerpt: string) => void; t: Translate; format: Format }) {
  const markdown = detail.markdown_text ?? "";
  const list = useMemo(() => contentChecklist(markdown), [markdown]);
  const pages = detail.document_layout?.pages.length ?? 0;
  const lowConfidence = (detail.pipeline?.steps ?? []).flatMap(step => {
    const warnings = (step as { ocr_warnings?: Array<{ page?: number; message?: string }> }).ocr_warnings;
    return Array.isArray(warnings) ? warnings : [];
  });
  const row = (label: string, value: string | number) => <div className="station-check-row"><span>{label}</span><strong>{value}</strong></div>;
  const items = (entries: ChecklistItem[]) => entries.length ? (
    <ul className="station-check-items">{entries.slice(0, 50).map(item => (
      <li key={item.key}><button className="text-link" onClick={() => onLocate(item.excerpt)} type="button"><FileText size={14} /> {item.excerpt}</button></li>
    ))}</ul>
  ) : <small className="field-note">{t("stationChecklistNone")}</small>;
  return (
    <div className="station-checklist">
      {row(t("stationChecklistPages"), pages || "-")}
      {row(t("stationChecklistCharacters"), list.characters)}
      {row(t("stationChecklistTables"), list.tables.length)}
      {items(list.tables)}
      {row(t("stationChecklistImages"), list.images.length)}
      {items(list.images)}
      {row(t("stationChecklistLowConfidence"), lowConfidence.length)}
      {lowConfidence.length ? <ul className="station-check-items">{lowConfidence.slice(0, 50).map((warning, index) => (
        <li key={index}>{format("stationChecklistLowConfidenceItem", { page: warning.page ?? "-", message: warning.message ?? "" })}</li>
      ))}</ul> : <small className="field-note">{t("stationChecklistNone")}</small>}
      <small className="field-note">{t("stationChecklistEditHint")}</small>
    </div>
  );
}

/** Scroll the viewer to the first occurrence of `excerpt` and select it (check list "locate"). */
export function locateText(viewer: HTMLElement | null, excerpt: string): boolean {
  if (!viewer || !excerpt) return false;
  const walker = document.createTreeWalker(viewer, NodeFilter.SHOW_TEXT);
  const needle = excerpt.slice(0, 20);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const index = node.textContent?.indexOf(needle) ?? -1;
    if (index < 0) continue;
    const range = document.createRange();
    range.setStart(node, index);
    range.setEnd(node, index + needle.length);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    node.parentElement?.scrollIntoView({ block: "center" });
    return true;
  }
  return false;
}

/** CHUNK442-003: overlap banner with the "only overlapping" filter. */
export function OverlapBanner({ count, onlyOverlap, onToggle, t, format }: { count: number; onlyOverlap: boolean; onToggle: (value: boolean) => void; t: Translate; format: Format }) {
  if (!count) return null;
  return (
    <div className="review-banner warning overlap-banner" role="status">
      <AlertTriangle size={18} />
      <span>{format("overlapBanner", { count })}</span>
      <label className="overlap-filter"><input checked={onlyOverlap} onChange={event => onToggle(event.target.checked)} type="checkbox" /> {t("overlapFilter")}</label>
    </div>
  );
}

const REFERENCE_STATUS: Record<ChunkReferenceItem["status"], TranslationKey> = { resolved: "referencesStatusResolved", unresolved: "referencesStatusUnresolved", external: "referencesStatusExternal" };

/** STAGE442-007 / REF442-003: references of the selected chunk, with assign, external, unresolve, delete and add. */
export function ChunkReferencePanel({ apiFetch, projectId, detail, chunkId, editable, onlyUnresolved, onOnlyUnresolved, onSelectChunk, t, format }: {
  apiFetch: ApiFetch; projectId: string; detail: KnowledgeDetailResponse; chunkId: string | null; editable: boolean;
  onlyUnresolved: boolean; onOnlyUnresolved: (value: boolean) => void; onSelectChunk: (chunkId: string) => void; t: Translate; format: Format;
}) {
  const [items, setItems] = useState<ChunkReferenceItem[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [draftRelation, setDraftRelation] = useState<"references" | "supersedes">("references");
  const [revision, setRevision] = useState(0);
  const versionId = detail.version.id;
  const documentId = detail.document.id;

  useEffect(() => {
    const controller = new AbortController();
    listChunkReferences(apiFetch, projectId, documentId, versionId, controller.signal)
      .then(response => { setItems(response.items); setLoadError(false); })
      .catch(error => { if (!(error instanceof DOMException && error.name === "AbortError")) setLoadError(true); });
    return () => controller.abort();
  }, [apiFetch, projectId, documentId, versionId, revision]);

  useEffect(() => {
    if (!editable) return;
    const controller = new AbortController();
    listProjectDocuments(apiFetch, projectId, controller.signal).then(setDocuments).catch(() => setDocuments([]));
    return () => controller.abort();
  }, [apiFetch, projectId, editable]);

  const live = items.filter(item => !item.is_deleted);
  const unresolved = live.filter(item => item.status === "unresolved");
  const shown = onlyUnresolved ? unresolved : live.filter(item => item.chunk_id === chunkId);
  const targets = documents.filter(item => item.id !== documentId && item.status !== "deleted");

  async function run(key: string, action: () => Promise<unknown>) {
    setBusy(key); setActionError(null);
    try { await action(); setRevision(value => value + 1); }
    catch (error) { setActionError(operationalErrorMessage(error, t, format, "referencesActionFailed")); }
    finally { setBusy(null); }
  }

  return (
    <div className="chunk-reference-panel">
      <div className="chunk-reference-head">
        <strong><Link2 size={15} /> {t("referencesTitle")}</strong>
        <small>{format("referencesSummary", { total: live.length, unresolved: unresolved.length })}</small>
        <label className="overlap-filter"><input checked={onlyUnresolved} onChange={event => onOnlyUnresolved(event.target.checked)} type="checkbox" /> {t("referencesUnresolvedOnly")}</label>
      </div>
      {loadError ? <FeedbackMessage tone="error">{t("referencesLoadFailed")}</FeedbackMessage> : null}
      {!onlyUnresolved && !chunkId ? <small className="field-note">{t("referencesSelectChunk")}</small> : null}
      {(onlyUnresolved || chunkId) && !shown.length && !loadError ? <small className="field-note">{t(onlyUnresolved ? "referencesNoUnresolved" : "referencesEmpty")}</small> : null}
      <ul className="chunk-reference-list">
        {shown.map(item => (
          <li key={item.id}>
            <div className="chunk-reference-line">
              {onlyUnresolved && item.chunk_index ? <button className="chunk-index-badge" onClick={() => onSelectChunk(item.chunk_id)} type="button">#{item.chunk_index}</button> : null}
              <span className={`chunk-relation-badge relation-${item.relation_type ?? "references"}`}>{t(item.relation_type === "supersedes" ? "referencesRelationSupersedes" : "referencesRelationReferences")}</span>
              <span className="chunk-reference-text">{item.raw_text}</span>
              <span className={`status-badge feedback-status-badge feedback-${item.status === "unresolved" ? "warning" : item.status === "resolved" ? "success" : "info"}`}>{t(REFERENCE_STATUS[item.status])}</span>
              {item.target_title ? <small>→ {item.target_title}</small> : null}
            </div>
            {editable ? (
              <div className="chunk-reference-actions">
                <select aria-label={t("referencesAssign")} disabled={busy !== null} onChange={event => event.target.value && void run(`${item.id}:assign`, () => updateChunkReference(apiFetch, projectId, documentId, versionId, item.id, { lock_version: item.lock_version, action: "assign", target_document_id: event.target.value }))} value="">
                  <option value="">{t("referencesTargetPlaceholder")}</option>
                  {targets.map(target => <option key={target.id} value={target.id}>{target.title}</option>)}
                </select>
                {item.status !== "external" ? <button className="action-button secondary compact" disabled={busy !== null} onClick={() => void run(`${item.id}:external`, () => updateChunkReference(apiFetch, projectId, documentId, versionId, item.id, { lock_version: item.lock_version, action: "external" }))} type="button">{t("referencesMarkExternal")}</button> : null}
                {item.status !== "unresolved" ? <button className="action-button secondary compact" disabled={busy !== null} onClick={() => void run(`${item.id}:unresolve`, () => updateChunkReference(apiFetch, projectId, documentId, versionId, item.id, { lock_version: item.lock_version, action: "unresolve" }))} type="button">{t("referencesUnresolve")}</button> : null}
                <button aria-label={t("referencesDelete")} className="icon-button" disabled={busy !== null} onClick={() => void run(`${item.id}:delete`, () => deleteChunkReference(apiFetch, projectId, documentId, versionId, item.id, item.lock_version))} title={t("referencesDelete")} type="button"><Trash2 size={15} /></button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {editable && chunkId && !onlyUnresolved ? (
        <form className="chunk-reference-add" onSubmit={event => { event.preventDefault(); const text = draft.trim(); if (text) void run("add", async () => { await createChunkReference(apiFetch, projectId, documentId, versionId, { chunk_id: chunkId, raw_text: text, relation_type: draftRelation }); setDraft(""); }); }}>
          <select aria-label={t("referencesRelationLabel")} disabled={busy !== null} onChange={event => setDraftRelation(event.target.value as "references" | "supersedes")} value={draftRelation}>
            <option value="references">{t("referencesRelationReferences")}</option>
            <option value="supersedes">{t("referencesRelationSupersedes")}</option>
          </select>
          <input aria-label={t("referencesRawTextLabel")} disabled={busy !== null} maxLength={500} onChange={event => setDraft(event.target.value)} placeholder={t("referencesRawTextLabel")} value={draft} />
          <button className="action-button secondary compact" disabled={busy !== null || !draft.trim()} type="submit">{t("referencesAdd")}</button>
        </form>
      ) : null}
      {actionError ? <FeedbackMessage tone="error">{actionError}</FeedbackMessage> : null}
    </div>
  );
}
