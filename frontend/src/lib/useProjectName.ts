"use client";

import { useEffect, useState } from "react";
import { getProject, type ApiFetch } from "@/lib/api";

/**
 * CHG-495 M15 (DESIGN.md §6): the project name for the breadcrumb of document pages. The read is
 * best effort: on failure the caller shows a generic label, and the page itself does not depend on it.
 */
export function useProjectName(apiFetch: ApiFetch, projectId: string, enabled: boolean): string | null {
  const [loaded, setLoaded] = useState<{ projectId: string; name: string } | null>(null);
  useEffect(() => {
    if (!enabled || !projectId) return;
    const controller = new AbortController();
    getProject(apiFetch, projectId, controller.signal)
      .then((project) => { if (!controller.signal.aborted) setLoaded({ projectId, name: project.name }); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [apiFetch, projectId, enabled]);
  return loaded?.projectId === projectId ? loaded.name : null;
}
