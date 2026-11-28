"use client";

import { useCallback, useId } from "react";
import { FilePen, Link2, Minus, Plus, Tags } from "lucide-react";
import { getApprovalVersionChanges, type ApiError, type ApiFetch, type ApprovalVersionChanges } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { useReadResource } from "@/lib/useReadResource";

function NameChanges({ added, removed, icon: Icon, title }: { added: string[]; removed: string[]; icon: typeof Tags; title: string }) {
  const { t } = useI18n();
  return (
    <section className="approval-changes-block">
      <h4><Icon aria-hidden="true" size={14} />{title}</h4>
      {added.length || removed.length ? <ul className="approval-changes-names">
        {added.map((name) => <li className="is-added" key={`added:${name}`}><Plus aria-hidden="true" size={12} /><span className="sr-only">{t("approvalChangesLineAdded")}</span>{name}</li>)}
        {removed.map((name) => <li className="is-removed" key={`removed:${name}`}><Minus aria-hidden="true" size={12} /><span className="sr-only">{t("approvalChangesLineRemoved")}</span><del>{name}</del></li>)}
      </ul> : <p className="approval-changes-note">{t("approvalChangesNone")}</p>}
    </section>
  );
}

/** CHG-495 M22 (K201): pure rendering of `GET /approvals/{id}/changes`. */
export function ApprovalVersionChangesView({ changes }: { changes: ApprovalVersionChanges }) {
  const { t, format } = useI18n();
  const titleId = useId();
  return (
    <section aria-labelledby={titleId} className="approval-side-card approval-changes">
      <h3 id={titleId}><FilePen aria-hidden="true" size={16} />{t("approvalChangesTitle")}</h3>
      {changes.first_submission ? <p className="approval-changes-note">{t("approvalChangesFirstSubmission")}</p> : <>
        <p className="approval-changes-note">{format("approvalChangesComparedWith", { version: changes.previous_version_label ?? t("approvalChangesPreviousPublished") })}</p>
        <section className="approval-changes-block">
          <h4><FilePen aria-hidden="true" size={14} />{t("approvalChangesText")}{changes.text_status === "available" ? <small>{format("approvalChangesLineCounts", { added: changes.lines_added, removed: changes.lines_removed })}</small> : null}</h4>
          {changes.text_status === "unchanged" ? <p className="approval-changes-note">{t("approvalChangesTextUnchanged")}</p>
            : changes.text_status === "unavailable" ? <p className="approval-changes-note">{t("approvalChangesTextUnavailable")}</p>
              : <ol className="approval-changes-lines">
                {changes.text_changes.map((line, index) => <li className={line.op === "added" ? "is-added" : "is-removed"} key={`${index}:${line.op}`}>
                  <span aria-hidden="true" className="approval-changes-sign">{line.op === "added" ? "+" : "−"}</span>
                  <span className="sr-only">{t(line.op === "added" ? "approvalChangesLineAdded" : "approvalChangesLineRemoved")}</span>
                  {line.op === "removed" ? <del>{line.text}</del> : <ins>{line.text}</ins>}
                </li>)}
              </ol>}
          {changes.text_status === "available" && changes.text_changes_truncated ? <p className="approval-changes-note" role="note">{t("approvalChangesTruncated")}</p> : null}
        </section>
        <NameChanges added={changes.tags.added} icon={Tags} removed={changes.tags.removed} title={t("approvalChangesTags")} />
        <NameChanges added={changes.references.added} icon={Link2} removed={changes.references.removed} title={t("approvalChangesReferences")} />
      </>}
    </section>
  );
}

/** Loads the changes for one approval task; a reader without access (403) sees nothing. */
export function ApprovalVersionChangesSection({ apiFetch, approvalTaskId }: { apiFetch: ApiFetch; approvalTaskId: string }) {
  const { t } = useI18n();
  const read = useCallback((signal: AbortSignal) => getApprovalVersionChanges(apiFetch, approvalTaskId, signal), [apiFetch, approvalTaskId]);
  const changes = useReadResource(read, approvalTaskId, Boolean(approvalTaskId));
  if (changes.status === "ready" && changes.data) return <ApprovalVersionChangesView changes={changes.data} />;
  if (changes.status === "error" && (changes.error as Partial<ApiError>)?.status === 403) return null;
  return (
    <section aria-busy={changes.status === "loading"} className="approval-side-card approval-changes">
      <h3><FilePen aria-hidden="true" size={16} />{t("approvalChangesTitle")}</h3>
      {changes.status === "error" ? <p className="approval-changes-note" role="status">{t("approvalChangesLoadFailed")} <button className="text-link" onClick={() => { void changes.reload(); }} type="button">{t("uiReadRetry")}</button></p>
        : <p className="approval-changes-note" role="status">{t("approvalChangesLoading")}</p>}
    </section>
  );
}
