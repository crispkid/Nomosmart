"use client";

import { useLayoutEffect, useRef } from "react";

const dialogSelector = '[role="dialog"][aria-modal="true"], [role="alertdialog"][aria-modal="true"]';
const controlSelector = 'button, a[href], input:not([type="hidden"]), select, textarea, [tabindex]';

function visible(element: HTMLElement) {
  return element.isConnected && !element.closest('[hidden], [inert], [aria-hidden="true"]')
    && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";
}
function controls(dialog: HTMLElement) {
  return [...dialog.querySelectorAll<HTMLElement>(controlSelector)]
    .filter((element) => element.tabIndex >= 0 && !element.matches(":disabled") && visible(element));
}
function topDialog() {
  return [...document.querySelectorAll<HTMLElement>(dialogSelector)].filter(visible).at(-1);
}
function focusStart(dialog: HTMLElement) {
  (controls(dialog)[0] ?? dialog).focus();
}

/** Scoped to the P1 dialogs; only the visible top dialog owns keyboard focus. */
export function useModalFocus(active: boolean, onEscape: () => void) {
  const ref = useRef<HTMLElement>(null);
  const close = useRef(onEscape);
  useLayoutEffect(() => { close.current = onEscape; });
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!active || !dialog) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (topDialog() === dialog) focusStart(dialog);
    function keydown(event: KeyboardEvent) {
      if (!dialog || topDialog() !== dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close.current();
      } else if (event.key === "Tab") {
        const items = controls(dialog);
        const index = items.indexOf(document.activeElement as HTMLElement);
        if (!items.length || index < 0 || (!event.shiftKey && index === items.length - 1) || (event.shiftKey && index === 0)) {
          event.preventDefault();
          (event.shiftKey ? items.at(-1) ?? dialog : items[0] ?? dialog).focus();
        }
      }
    }
    function focusin(event: FocusEvent) {
      if (dialog && topDialog() === dialog && event.target instanceof Node && !dialog.contains(event.target)) focusStart(dialog);
    }
    document.addEventListener("keydown", keydown, true);
    document.addEventListener("focusin", focusin);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.removeEventListener("focusin", focusin);
      queueMicrotask(() => {
        const parent = topDialog();
        if (previous && visible(previous) && !previous.matches(":disabled") && (!parent || parent.contains(previous))) previous.focus();
        else if (parent) focusStart(parent);
        else document.querySelector<HTMLElement>(".project-context a, main a[href], main button:not(:disabled)")?.focus();
      });
    };
  }, [active]);
  return ref;
}
