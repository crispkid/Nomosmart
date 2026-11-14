"use client";

import { useI18n } from "@/lib/i18nClient";


export function AIModelCredentialClearControl({
  clearDraft,
  configured,
  confirmation,
  modelName,
  onClearChange,
  onConfirmationChange,
}: {
  clearDraft: boolean;
  configured: boolean;
  confirmation: string;
  modelName: string;
  onClearChange: (checked: boolean) => void;
  onConfirmationChange: (value: string) => void;
}) {
  const { t, format } = useI18n();
  if (!configured) return null;
  return <div className="system-model-pairing">
    <label className="identity-toggle"><input checked={clearDraft} name="clear_credential" onChange={(event) => onClearChange(event.target.checked)} type="checkbox" /><span>{t("systemModelCredentialClear")}</span></label>
    <p>{t("systemModelCredentialClearHelp")}</p>
    {clearDraft ? <label><span>{format("systemModelCredentialClearConfirmation", { name: modelName })}</span><input autoComplete="off" onChange={(event) => onConfirmationChange(event.target.value)} placeholder={modelName} value={confirmation} /></label> : null}
  </div>;
}
