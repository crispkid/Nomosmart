"use client";

import { MessageSquare, MessagesSquare } from "lucide-react";
import type { ConversationMode } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";

/** CHG-435 MTURN435-011: choose single- or multi-turn for a new conversation; fixed after the first question. */
export function ChatModePicker({ mode, locked, onChange }: { mode: ConversationMode; locked: boolean; onChange: (mode: ConversationMode) => void }) {
  const { t } = useI18n();
  return (
    <div className="chat-mode-picker" role="group" aria-label={t("chatModeLabel")}>
      <span className="chat-mode-label">{t("chatModeLabel")}</span>
      <button aria-pressed={mode === "single"} className={mode === "single" ? "selected" : ""} disabled={locked} onClick={() => onChange("single")} type="button"><MessageSquare size={14} /> {t("chatModeSingle")}</button>
      <button aria-pressed={mode === "multi"} className={mode === "multi" ? "selected" : ""} disabled={locked} onClick={() => onChange("multi")} type="button"><MessagesSquare size={14} /> {t("chatModeMulti")}</button>
      {locked ? <small>{t("chatModeLockedHint")}</small> : null}
    </div>
  );
}
