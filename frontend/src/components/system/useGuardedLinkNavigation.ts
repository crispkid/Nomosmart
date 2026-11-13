"use client";

import { useEffect } from "react";
import { apiBaseUrl } from "@/lib/oidc";

type GuardedLinkInput = {
  apiFetch: (input: string, init?: RequestInit) => Promise<Response>;
  identityActive: boolean;
  promptEditorOpen: boolean;
  requestPromptLeave: (action: () => void) => void;
  requestSettingsLeave: (action: () => void) => void;
  setSystemError: (error: Error) => void;
  unsaved: boolean;
};

/**
 * Intercepts same-origin link clicks while settings have unsaved changes or the identity
 * settings lock is held, asking before leaving and releasing the lock first (OPT424-038).
 */
export function useGuardedLinkNavigation({ apiFetch, identityActive, promptEditorOpen, requestPromptLeave, requestSettingsLeave, setSystemError, unsaved }: GuardedLinkInput) {
  useEffect(() => {
    const followLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.target || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (!unsaved && !promptEditorOpen && !identityActive) return;
      event.preventDefault(); event.stopPropagation();
      const go = () => {
        if (identityActive) void apiFetch(`${apiBaseUrl()}/system/identity-settings/lock`, { method: "POST" }).then(response => {
          if (!response.ok) throw new Error("identity_settings_locked"); window.location.assign(url.href);
        }).catch(error => setSystemError(error));
        else window.location.assign(url.href);
      };
      if (promptEditorOpen) requestPromptLeave(go); else requestSettingsLeave(go);
    };
    document.addEventListener("click", followLink, true);
    return () => document.removeEventListener("click", followLink, true);
  });
}
