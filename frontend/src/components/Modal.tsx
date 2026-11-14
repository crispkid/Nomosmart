"use client";

import type { HTMLAttributes, ReactNode } from "react";
import { useModalFocus } from "@/components/useModalFocus";

type ModalProps = Omit<HTMLAttributes<HTMLElement>, "role" | "className" | "children"> & {
  /** Esc handler; each dialog keeps its own close rules (for example, ignore while busy). */
  onEscape: () => void;
  /** Called when the pointer goes down on the backdrop itself, not on the dialog. */
  onBackdropMouseDown?: () => void;
  role?: "dialog" | "alertdialog";
  /** Classes of the dialog container, e.g. `modal-panel create-project-modal`. */
  className: string;
  backdropClassName?: "modal-backdrop" | "system-modal-backdrop";
  children: ReactNode;
};

/**
 * Shared dialog shell (OPT424-032, D424-20). Mount it only while the dialog is
 * open: it renders the backdrop and the modal container and runs
 * {@link useModalFocus} (focus moves in, Tab stays inside, Esc calls
 * `onEscape`, focus returns to the opener on close). Header and body stay with
 * the caller, so existing classes and layout are unchanged.
 */
export function Modal({ onEscape, onBackdropMouseDown, role = "dialog", className, backdropClassName = "modal-backdrop", children, ...section }: ModalProps) {
  const dialogRef = useModalFocus(true, onEscape);
  return <div className={backdropClassName} onMouseDown={onBackdropMouseDown ? (event) => { if (event.target === event.currentTarget) onBackdropMouseDown(); } : undefined} role="presentation">
    <section {...section} aria-modal="true" className={className} ref={dialogRef} role={role} tabIndex={-1}>{children}</section>
  </div>;
}
