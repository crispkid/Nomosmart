"use client";

import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";
import type { FeedbackTone } from "@/lib/feedback";
import { useI18n } from "@/lib/i18nClient";

export const feedbackIcons = { success: CheckCircle2, info: Info, warning: AlertTriangle, error: AlertCircle };

export function FeedbackMessage({ tone = "error", title, children, actions, critical = false, className = "", announce = true }: {
  tone?: FeedbackTone; title?: ReactNode; children?: ReactNode; actions?: ReactNode;
  critical?: boolean; className?: string; announce?: boolean;
}) {
  const { t } = useI18n();
  const Icon = feedbackIcons[tone];
  return <div className={`feedback-message feedback-${tone} ${className}`} role={announce ? (tone === "error" ? "alert" : "status") : undefined}>
    <Icon className="feedback-icon" size={20} aria-hidden="true" />
    <div className="feedback-copy">
      <strong>{critical ? <span className="feedback-critical">{t("feedbackCritical")} · </span> : null}{title ?? t(tone === "error" ? "feedbackErrorTitle" : tone === "warning" ? "feedbackWarningTitle" : tone === "success" ? "feedbackSuccessTitle" : "feedbackInfoTitle")}</strong>
      {children ? <div className="feedback-description">{children}</div> : null}
    </div>
    {actions ? <div className="feedback-actions">{actions}</div> : null}
  </div>;
}

export function FeedbackField({ id, children }: { id?: string; children: ReactNode }) {
  return <span id={id} className="feedback-field"><AlertCircle size={14} aria-hidden="true" />{children}</span>;
}

export function FeedbackSeverityBadge({ severity }: { severity: string }) {
  const { t } = useI18n();
  const tone = severity === "critical" || severity === "error" ? "error" : severity === "warning" ? "warning" : severity === "success" ? "success" : "info";
  const Icon = feedbackIcons[tone];
  return <span className={`feedback-status-badge feedback-${tone}`}><Icon size={14} aria-hidden="true" />{t(severity === "critical" ? "feedbackCritical" : tone === "error" ? "feedbackSeverityError" : tone === "warning" ? "feedbackSeverityWarning" : tone === "success" ? "feedbackSeveritySuccess" : "feedbackSeverityInfo")}</span>;
}
