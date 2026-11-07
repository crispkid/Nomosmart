"use client";

import { DropdownSelect } from "@/components/DropdownSelect";

import { useId } from "react";
import { useI18n } from "@/lib/i18nClient";

type VersionOption = { id: string; version_label: string; status: string };

export function ReferenceVersionSelect({ documentTitle, disabled, description, loading, value, versions, onChange }: {
  documentTitle: string; disabled: boolean; description: string; loading: boolean;
  value: string; versions: VersionOption[]; onChange: (value: string) => void;
}) {
  const id = useId();
  const { t, format } = useI18n();
  return <span className="reference-version-select">
    <label className="sr-only" htmlFor={id}>{format("referenceVersionSelectLabel", { title: documentTitle })}</label>
    <DropdownSelect aria-describedby={`${id}-help`} disabled={disabled} id={id} onChange={event => onChange(event.target.value)} value={value}>
      <option value="">{loading ? t("loadingData") : t("projectImportSelectReferenceVersion")}</option>
      {versions.map(version => <option key={version.id} value={version.id}>{version.version_label} · {version.status}</option>)}
    </DropdownSelect>
    <span className="sr-only" id={`${id}-help`}>{description}</span>
  </span>;
}
