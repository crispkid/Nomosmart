"use client";

import type { ChatTurnContext } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";

/** CHG-435 MTURN435-011: what earlier context a multi-turn answer used. */
export function ChatTurnContextNote({ context }: { context?: ChatTurnContext | null }) {
  const { t, format } = useI18n();
  if (!context || (!context.turns_used && context.rewrite_status === "not_needed")) return null;
  return (
    <ul className="chat-turn-context">
      {context.turns_used ? <li>{format("chatContextTurns", { count: context.turns_used })}</li> : null}
      {context.rewritten_query ? <li>{format("chatContextRewritten", { query: context.rewritten_query })}</li> : null}
      {context.truncated ? <li>{t("chatContextTruncated")}</li> : null}
      {context.rewrite_status === "failed" ? <li>{t("chatContextRewriteFailed")}</li> : null}
    </ul>
  );
}

export function recordTurnContext(record: { history_turns?: number; history_truncated?: boolean; rewritten_query?: string | null; rewrite_status?: ChatTurnContext["rewrite_status"] }): ChatTurnContext {
  return { turns_used: record.history_turns ?? 0, truncated: Boolean(record.history_truncated), rewritten_query: record.rewritten_query ?? null, rewrite_status: record.rewrite_status ?? "not_needed" };
}
