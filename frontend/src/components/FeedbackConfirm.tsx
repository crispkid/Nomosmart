"use client";

import { useId, type ReactNode } from "react";
import { FeedbackMessage } from "./FeedbackMessage";

/** Inline confirmation stays inside its existing dialog and its focus trap. */
export function FeedbackConfirm({ title, children, cancelLabel, confirmLabel, onCancel, onConfirm, busy = false }: {
  title: ReactNode; children?: ReactNode; cancelLabel: string; confirmLabel: string;
  onCancel: () => void; onConfirm: () => void; busy?: boolean;
}) {
  const id = useId();
  return <div className="feedback-confirm" role="group" aria-labelledby={id}>
    <FeedbackMessage tone="warning" title={<span id={id}>{title}</span>} actions={<>
      <button autoFocus className="action-button secondary" type="button" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
      <button className="action-button danger" type="button" disabled={busy} onClick={onConfirm}>{confirmLabel}</button>
    </>}>{children}</FeedbackMessage>
  </div>;
}
