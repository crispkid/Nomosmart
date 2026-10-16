"use client";

import { useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes } from "react";
import { createPortal } from "react-dom";

export function IconActionButton({ label, className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });

  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      if (!button.current || !tooltip.current) return;
      const anchor = button.current.getBoundingClientRect();
      const tip = tooltip.current.getBoundingClientRect();
      if (anchor.right <= 0 || anchor.left >= window.innerWidth || anchor.bottom <= 0 || anchor.top >= window.innerHeight) {
        setOpen(false);
        return;
      }
      setPosition({
        left: Math.max(12, Math.min(anchor.left + (anchor.width - tip.width) / 2, window.innerWidth - tip.width - 12)),
        top: anchor.bottom + tip.height + 8 <= window.innerHeight ? anchor.bottom + 8 : Math.max(8, anchor.top - tip.height - 8),
      });
    }
    function dismiss(event: KeyboardEvent) { if (event.key === "Escape") setOpen(false); }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.addEventListener("keydown", dismiss);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("keydown", dismiss);
    };
  }, [open, label]);

  return <>
    <button {...props} ref={button} type={props.type ?? "button"} className={`${className} icon-action-button`} aria-label={label}
      aria-describedby={[props["aria-describedby"], open ? id : undefined].filter(Boolean).join(" ") || undefined}
      onMouseEnter={event => { setOpen(true); props.onMouseEnter?.(event); }}
      onMouseLeave={event => { if (document.activeElement !== button.current) setOpen(false); props.onMouseLeave?.(event); }}
      onFocus={event => { setOpen(true); props.onFocus?.(event); }}
      onBlur={event => { setOpen(false); props.onBlur?.(event); }}>
      {children}
    </button>
    {open ? createPortal(<div ref={tooltip} id={id} role="tooltip" className="icon-action-tooltip" style={position}>{label}</div>, document.body) : null}
  </>;
}
