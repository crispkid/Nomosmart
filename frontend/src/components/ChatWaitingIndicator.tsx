"use client";

import { LoaderCircle } from "lucide-react";

export function ChatWaitingIndicator({ label }: { label: string }) {
  return (
    <div aria-busy="true" aria-live="polite" className="chat-waiting-status" role="status">
      <LoaderCircle aria-hidden="true" className="chat-waiting-spinner" size={18} />
      <span>{label}</span>
    </div>
  );
}
