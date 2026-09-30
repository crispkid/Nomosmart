import { elapsedUnits, pipelineElapsed, type ElapsedPipeline } from "@/lib/pipelineElapsed";
import { formatTranslation, t, type Locale } from "@/lib/i18n";

/** Plain text, not aria-live: elapsed seconds should not interrupt screen readers. */
export function PipelineElapsed({ pipeline, now, enabled, locale }: {
  pipeline: ElapsedPipeline; now: number; enabled: boolean; locale: Locale;
}) {
  const elapsed = pipelineElapsed(pipeline, now, enabled);
  const unknown = elapsed.kind === "unknown";
  return <span title={unknown ? t("pipelineElapsedUnavailable", locale) : undefined}>
    {t("pipelineElapsed", locale)}：{unknown ? "—" : formatTranslation("pipelineElapsedDuration", elapsedUnits(elapsed.seconds), locale)}
  </span>;
}
