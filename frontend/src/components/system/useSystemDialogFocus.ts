"use client";

import { useEffect, useRef, type RefObject } from "react";
import type { ModalState } from "./modalState";

type DialogFocusInput = {
  activeTab: string;
  apiKeyDialogRef: RefObject<HTMLElement | null>;
  apiKeyOneTimeOpen: boolean;
  modal: ModalState | null;
  navigationRef: RefObject<HTMLElement | null>;
  promptEditorOpen: boolean;
};

/**
 * Remembers the control that opened a system dialog and returns focus to it when the CRUD modal,
 * the one-time API key dialog or the prompt editor closes (OPT424-038).
 */
export function useSystemDialogFocus({ activeTab, apiKeyDialogRef, apiKeyOneTimeOpen, modal, navigationRef, promptEditorOpen }: DialogFocusInput) {
  const systemDialogRef = useRef<HTMLElement>(null);
  const systemDialogTriggerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const remember = (event: FocusEvent) => { if (event.target instanceof HTMLElement && !event.target.closest('[role="dialog"],[role="alertdialog"]')) systemDialogTriggerRef.current = event.target; };
    document.addEventListener("focusin", remember);
    return () => document.removeEventListener("focusin", remember);
  }, []);
  useEffect(() => {
    if (!modal) return;
    const dialog = systemDialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) dialog.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    const trigger = systemDialogTriggerRef.current;
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, [modal]);
  useEffect(() => {
    if (!apiKeyOneTimeOpen || modal) return;
    const trigger = systemDialogTriggerRef.current;
    const fallback = navigationRef.current?.querySelector<HTMLButtonElement>("nav button[aria-current]");
    apiKeyDialogRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [apiKeyOneTimeOpen, modal, activeTab, navigationRef, apiKeyDialogRef]);
  useEffect(() => {
    if (!promptEditorOpen) return;
    const trigger = systemDialogTriggerRef.current;
    const fallback = navigationRef.current?.querySelector<HTMLButtonElement>("nav button[aria-current]");
    return () => {
      if (trigger?.isConnected) trigger.focus();
      else if (fallback?.isConnected) fallback.focus();
    };
  }, [promptEditorOpen, navigationRef]);
  return systemDialogRef;
}
