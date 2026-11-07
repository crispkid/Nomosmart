"use client";
import type { ChunkingIssue } from "@/lib/api";
import { useI18n } from "@/lib/i18nClient";
import { formatCount } from "@/lib/numberFormat";
import { operationalCodeMessage } from "@/lib/operationalMessages";

export function ChunkingIssueSummary({ issue }: { issue?: ChunkingIssue | null }) {
  const { t, format, locale } = useI18n();
  if (!issue) return null;
  return <div className="pipeline-meta chunking-issue-summary" role="status" aria-live="polite">
    <strong>{t("chunkContentNeedsAdjustment")}</strong>
    <span>{operationalCodeMessage(issue.code, t, format, "apiGenericError")}</span>
    {issue.row_start != null && issue.row_end != null ? <span>{format("chunkIssueRows", {
      start: formatCount(issue.row_start, locale), end: formatCount(issue.row_end, locale)
    })}</span> : null}
    {issue.input_tokens != null && issue.input_token_limit != null ? <span>{format("chunkIssueInputLimit", {
      used: formatCount(issue.input_tokens, locale), limit: formatCount(issue.input_token_limit, locale)
    })}</span> : null}
    <span>{t(issue.action_required === "configure_model" ? "chunkIssueConfigureModel" : issue.can_edit_content ? "chunkIssueEditHelp" : "chunkIssueContactEditor")}</span>
  </div>;
}
