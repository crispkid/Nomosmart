"use client";

import { createPortal } from "react-dom";
import { useEffect, useRef, useState, type FormHTMLAttributes } from "react";
import { FeedbackField, FeedbackMessage } from "./FeedbackMessage";
import { useI18n, type TranslationKey } from "@/lib/i18nClient";

type Control = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
type Issue = { control: Control; host: HTMLSpanElement; key: TranslationKey; originalDescription: string | null; originalInvalid: string | null };
function removeIssue(issue: Issue) {
  issue.host.remove();
  if (issue.originalDescription === null) issue.control.removeAttribute("aria-describedby"); else issue.control.setAttribute("aria-describedby", issue.originalDescription);
  if (issue.originalInvalid === null) issue.control.removeAttribute("aria-invalid"); else issue.control.setAttribute("aria-invalid", issue.originalInvalid);
}

/** Native browser validity drives feedback; field values never enter message state. */
export function FeedbackForm({ children, onSubmit, onChange, outcomeUnknown = false, ...props }: FormHTMLAttributes<HTMLFormElement> & { outcomeUnknown?: boolean }) {
  const { t, format } = useI18n();
  const [issues, setIssues] = useState<Issue[]>([]);
  const issueRef = useRef<Issue[]>([]);
  useEffect(() => () => { issueRef.current.forEach(removeIssue); }, []);
  function clear() { issueRef.current.forEach(removeIssue); issueRef.current = []; }
  return <form {...props} noValidate onSubmit={event => {
    if (outcomeUnknown) { event.preventDefault(); return; }
    clear();
    const invalid = Array.from(event.currentTarget.elements).filter((element): element is Control =>
      (element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) && element.willValidate && !element.validity.valid);
    if (!invalid.length) { setIssues([]); onSubmit?.(event); return; }
    event.preventDefault();
    const next = invalid.map(control => {
      const host = document.createElement("span"); host.id = `feedback-field-${crypto.randomUUID()}`; host.className = "feedback-field-host";
      host.setAttribute("aria-hidden", "true"); // The explicit description reference reads it without changing the label.
      const originalDescription = control.getAttribute("aria-describedby"), originalInvalid = control.getAttribute("aria-invalid");
      control.insertAdjacentElement("afterend", host);
      control.setAttribute("aria-invalid", "true"); control.setAttribute("aria-describedby", [originalDescription, host.id].filter(Boolean).join(" "));
      const key: TranslationKey = control.validity.valueMissing ? "feedbackFieldRequired" : control.validity.typeMismatch ? "feedbackFieldType" : "feedbackFieldInvalid";
      return { control, host, key, originalDescription, originalInvalid };
    });
    issueRef.current = next; setIssues(next); invalid[0].focus();
  }} onChange={event => {
    const control: EventTarget = event.target;
    const cleared = issueRef.current.filter(item => item.control === control && item.control.validity.valid);
    if (cleared.length) { cleared.forEach(removeIssue); issueRef.current = issueRef.current.filter(item => !cleared.includes(item)); setIssues([...issueRef.current]); }
    onChange?.(event);
  }}>
    {issues.length ? <FeedbackMessage className="feedback-form-summary" title={format("feedbackFieldSummary", { count: issues.length })} actions={<button type="button" className="action-button secondary" onClick={() => issues[0]?.control.focus()}>{t("feedbackGoToField")}</button>} /> : null}
    <fieldset className="feedback-form-fields" disabled={outcomeUnknown}>{children}</fieldset>
    {issues.map(issue => createPortal(<FeedbackField>{t(issue.key)}</FeedbackField>, issue.host, issue.host.id))}
  </form>;
}
