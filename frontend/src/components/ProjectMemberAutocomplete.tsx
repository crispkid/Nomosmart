"use client";

import { useEffect, useRef, useState } from "react";

import type { ProjectMemberCandidate } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { formatPersonName } from "@/lib/personName";


type ProjectMemberAutocompleteProps = {
  candidates: ProjectMemberCandidate[];
  disabled?: boolean;
  id: string;
  label: string;
  locale: Locale;
  onQueryChange: (query: string) => void;
  onSelect: (candidate: ProjectMemberCandidate) => void;
  placeholder: string;
  statusMessage: string;
  value: string;
};


export function ProjectMemberAutocomplete({
  candidates,
  disabled = false,
  id,
  label,
  locale,
  onQueryChange,
  onSelect,
  placeholder,
  statusMessage,
  value,
}: ProjectMemberAutocompleteProps) {
  const [open, setOpen] = useState(false);
  const [activeCandidateId, setActiveCandidateId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const popupVisible = open && value.trim().length > 0;
  const activeIndex = candidates.findIndex((candidate) => candidate.id === activeCandidateId);
  const activeCandidate = activeIndex >= 0 ? candidates[activeIndex] : undefined;
  const activeOptionId = activeCandidate ? `${id}-option-${activeCandidate.id}` : undefined;

  useEffect(() => {
    if (activeIndex < 0) return;
    optionRefs.current[activeIndex]?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex]);

  function selectCandidate(candidate: ProjectMemberCandidate) {
    setOpen(false);
    setActiveCandidateId(null);
    onSelect(candidate);
    inputRef.current?.focus();
  }

  function moveActiveOption(direction: 1 | -1) {
    if (!candidates.length) return;
    setOpen(true);
    const nextIndex = activeIndex < 0
      ? (direction > 0 ? 0 : candidates.length - 1)
      : (activeIndex + direction + candidates.length) % candidates.length;
    setActiveCandidateId(candidates[nextIndex].id);
  }

  return (
    <div className="project-permission-autocomplete-control">
      <label htmlFor={id}>{label}</label>
      <div className="search-field project-permission-search-field">
        <input
          aria-activedescendant={popupVisible ? activeOptionId : undefined}
          aria-autocomplete="list"
          aria-controls={`${id}-options`}
          aria-expanded={popupVisible}
          aria-haspopup="listbox"
          autoComplete="off"
          disabled={disabled}
          id={id}
          onBlur={() => {
            setOpen(false);
            setActiveCandidateId(null);
          }}
          onChange={(event) => {
            onQueryChange(event.target.value);
            setOpen(true);
            setActiveCandidateId(null);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              moveActiveOption(1);
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              moveActiveOption(-1);
              return;
            }
            if (event.key === "Enter" && activeCandidate) {
              event.preventDefault();
              selectCandidate(activeCandidate);
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              setActiveCandidateId(null);
            }
          }}
          placeholder={placeholder}
          ref={inputRef}
          role="combobox"
          value={value}
        />
        {popupVisible ? (
          <div className="project-permission-autocomplete" id={`${id}-options`} role="listbox">
            {candidates.length ? (
              candidates.map((candidate, index) => (
                <button
                  aria-selected={activeIndex === index}
                  className={activeIndex === index ? "active" : undefined}
                  id={`${id}-option-${candidate.id}`}
                  key={candidate.id}
                  onClick={() => selectCandidate(candidate)}
                  onPointerDown={(event) => event.preventDefault()}
                  ref={(element) => { optionRefs.current[index] = element; }}
                  role="option"
                  tabIndex={-1}
                  type="button"
                >
                  <strong>{formatPersonName(candidate, locale)}</strong>
                  <span>{[candidate.email, candidate.employee_id].filter(Boolean).join(" · ") || candidate.id}</span>
                </button>
              ))
            ) : (
              <div aria-live="polite" className="project-permission-search-status" role="status">
                {statusMessage}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
