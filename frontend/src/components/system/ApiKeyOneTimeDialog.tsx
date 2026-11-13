"use client";

import type { RefObject } from "react";
import { KeyRound, X } from "lucide-react";
import type { TranslationKey } from "@/lib/i18nClient";

type ApiKeyOneTimeDialogProps = {
  apiKey: { name: string; key: string };
  dialogRef: RefObject<HTMLElement | null>;
  format: (key: TranslationKey, values: Record<string, string>) => string;
  onClose: () => void;
  t: (key: TranslationKey) => string;
};

/** One-time display of a newly issued API key (OPT424-038). */
export function ApiKeyOneTimeDialog({ apiKey, dialogRef, format, onClose, t }: ApiKeyOneTimeDialogProps) {
  return <div className="system-modal-backdrop" onKeyDown={(event) => {
    if (event.key === "Escape") { event.stopPropagation(); onClose(); }
    if (event.key === "Tab") {
      const dialog = dialogRef.current;
      const controls = Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]') ?? []).filter(control => control.getClientRects().length);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    }
  }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }} role="presentation">
    <section ref={dialogRef} aria-labelledby="system-api-key-onetime-title" aria-modal="true" className="system-reauth-modal system-api-key-onetime-modal" role="dialog">
      <header><span><KeyRound size={20} /></span><div><small>{t("systemApiKeys")}</small><h2 id="system-api-key-onetime-title">{format("systemApiKeyOneTimeTitle", { name: apiKey.name })}</h2></div><button aria-label={t("close")} className="modal-close-button" onClick={onClose} type="button"><X size={18} /></button></header>
      <div className="system-api-key-once" role="status"><KeyRound size={18} /><div><code>{apiKey.key}</code><small>{t("systemApiKeyOneTimeHelp")}</small></div></div>
      <footer><button className="action-button secondary" onClick={() => { void navigator.clipboard.writeText(apiKey.key); }} type="button">{t("systemApiKeyCopy")}</button><button className="action-button" onClick={onClose} type="button">{t("close")}</button></footer>
    </section>
  </div>;
}
