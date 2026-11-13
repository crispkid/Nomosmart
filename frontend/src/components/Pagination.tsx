"use client";

import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

type PaginationProps = {
  /** Existing layout class, e.g. project-pagination or report-pagination. */
  className: string;
  label?: string;
  summary: ReactNode;
  previousLabel: string;
  nextLabel: string;
  canPrevious: boolean;
  canNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  /** Text buttons show their labels; icon buttons keep them as accessible names. */
  variant?: "icon" | "text";
  buttonClassName?: string;
  leading?: ReactNode;
  iconSize?: number;
};

/** Shared previous/next pager (OPT424-032); pages keep their own summary text. */
export function Pagination({ className, label, summary, previousLabel, nextLabel, canPrevious, canNext, onPrevious, onNext,
  variant = "icon", buttonClassName, leading, iconSize = 16 }: PaginationProps) {
  const text = variant === "text";
  return (
    <nav aria-label={label} className={className}>
      {leading}
      <span>{summary}</span>
      <div>
        <button aria-label={text ? undefined : previousLabel} className={buttonClassName} disabled={!canPrevious} onClick={onPrevious} type="button">
          <ChevronLeft size={iconSize} />{text ? previousLabel : null}
        </button>
        <button aria-label={text ? undefined : nextLabel} className={buttonClassName} disabled={!canNext} onClick={onNext} type="button">
          {text ? nextLabel : null}<ChevronRight size={iconSize} />
        </button>
      </div>
    </nav>
  );
}
