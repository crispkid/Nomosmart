"use client";

import { useState } from "react";
import { CheckCircle2, LoaderCircle, Save } from "lucide-react";
import { FeedbackField, FeedbackMessage } from "@/components/FeedbackMessage";
import { getProject, updateProject, type ApiError, type ProjectResponse } from "@/lib/api";
import { formatCount } from "@/lib/numberFormat";
import { operationalErrorMessage } from "@/lib/operationalMessages";
import type { ImportPageDeps } from "./pageDeps";

type ProjectSettingsPanelProps = Pick<ImportPageDeps, "apiFetch" | "format" | "locale" | "t"> & {
  project: ProjectResponse;
  onSaved: (project: ProjectResponse) => void;
};

/**
 * CHG-495 M14: the project settings tab. Project Owners edit the name and description through the existing
 * `PUT /projects/{id}` (the backend still checks ownership); everyone else sees the same values read-only.
 * Models stay in System Management, so they are shown, not edited, here.
 */
export function ProjectSettingsPanel({ apiFetch, format, locale, project, onSaved, t }: ProjectSettingsPanelProps) {
  const canEdit = project.is_owner;
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [nameInvalid, setNameInvalid] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const dirty = name.trim() !== project.name || (description.trim() || null) !== (project.description || null);
  const owners = (project.owners ?? []).map((owner) => owner.display_name).filter(Boolean);

  async function save() {
    if (!canEdit || saving) return;
    if (!name.trim()) { setNameInvalid(true); return; }
    setSaving(true); setSaved(false); setError(null);
    try {
      await updateProject(apiFetch, project.id, { name: name.trim(), description: description.trim() || null, lock_version: project.lock_version });
      // The update response leaves out the overview fields (owners, counts); read the project again.
      const fresh = await getProject(apiFetch, project.id);
      onSaved(fresh);
      setName(fresh.name);
      setDescription(fresh.description ?? "");
      setSaved(true);
    } catch (caught) {
      setError(caught as ApiError | Error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="project-settings-title" className="project-tab-panel project-settings-tab">
      <section className="panel project-settings-section">
        <div className="panel-header">
          <div>
            <h2 id="project-settings-title">{t("projectSettingsInfoTitle")}</h2>
            <p>{t(canEdit ? "projectSettingsInfoHelp" : "projectSettingsOwnerOnly")}</p>
          </div>
        </div>
        {error ? <FeedbackMessage tone="error"><strong>{operationalErrorMessage(error, t, format, "apiGenericError")}</strong></FeedbackMessage> : null}
        {canEdit ? (
          <form className="project-settings-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
            <label>
              <span>{t("projectsName")}</span>
              <input aria-describedby={nameInvalid ? "project-settings-name-error" : undefined} aria-invalid={nameInvalid || undefined} disabled={saving} maxLength={255} onChange={(event) => { setName(event.target.value); setSaved(false); if (event.target.value.trim()) setNameInvalid(false); }} value={name} />
              {nameInvalid ? <FeedbackField id="project-settings-name-error">{t("projectsNameRequired")}</FeedbackField> : null}
            </label>
            <label>
              <span>{t("systemDescription")}</span>
              <textarea disabled={saving} onChange={(event) => { setDescription(event.target.value); setSaved(false); }} placeholder={t("projectsDescriptionPlaceholder")} value={description} />
            </label>
            <div className="project-settings-actions">
              {saved && !dirty ? <span className="project-settings-saved" role="status"><CheckCircle2 aria-hidden="true" size={16} />{t("systemSaved")}</span> : null}
              <button className="action-button" disabled={!dirty || saving} type="submit">{saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{t("save")}</button>
            </div>
          </form>
        ) : (
          <dl className="project-settings-list">
            <div><dt>{t("projectsName")}</dt><dd>{project.name}</dd></div>
            <div><dt>{t("systemDescription")}</dt><dd>{project.description || t("projectsNoDescription")}</dd></div>
          </dl>
        )}
      </section>
      <section className="panel project-settings-section">
        <div className="panel-header"><h2>{t("projectSettingsOverviewTitle")}</h2></div>
        <dl className="project-settings-list">
          <div><dt>{t("projectDetailSettingsOwners")}</dt><dd>{owners.length ? owners.join("、") : "—"}</dd></div>
          <div><dt>{t("projectSettingsReviewPath")}</dt><dd>{t("projectSettingsReviewPathValue")}</dd></div>
          <div><dt>{t("projectsModelCompleteness")}</dt><dd>{t(project.model_configuration_state === "ready" ? "projectsBasicReady" : "projectsBasicIncomplete")} · {t(`projectsPdfModel_${project.pdf_model_state}`)}<small>{t("projectDetailSettingsModelsHelp")}</small></dd></div>
          <div><dt>{t("projectSettingsCounts")}</dt><dd>{format("projectSettingsCountsValue", { documents: formatCount(project.document_count, locale), published: formatCount(project.published_document_count ?? 0, locale), chunks: formatCount(project.chunk_count ?? 0, locale) })}</dd></div>
        </dl>
      </section>
    </section>
  );
}
