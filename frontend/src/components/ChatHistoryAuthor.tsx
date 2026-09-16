"use client";

import { LockKeyhole, UserRound } from "lucide-react";
import { useI18n } from "@/lib/i18nClient";

export function ChatHistoryAuthor({ name, isMine, readOnly }: { name?: string | null; isMine: boolean; readOnly: boolean }) {
  const { t, format } = useI18n();
  const label = name?.trim() || t("chatAuthorNameMissing");
  return <span className="chat-history-author">
    <span title={label}><UserRound size={13} aria-hidden="true" />{format("chatAuthorName", { name: label })}{isMine ? ` · ${t("chatAuthorMe")}` : ""}</span>
    {readOnly ? <span><LockKeyhole size={13} aria-hidden="true" />{t(isMine ? "chatHistoryCannotContinue" : "chatHistoryReadOnly")}</span> : null}
  </span>;
}
