import type { Dispatch, SetStateAction } from "react";
import type { ApiFetch, CurrentUser, ProjectResponse } from "@/lib/api";
import type { Locale, TranslationKey } from "@/lib/i18nClient";
import type { Translate } from "./importDocumentModel";

/** Project import page values shared with its section modules (OPT424-038). */
export type ImportPageDeps = {
  apiFetch: ApiFetch;
  params: { id: string };
  t: Translate;
  format: (key: TranslationKey, params: Record<string, string | number>) => string;
  locale: Locale;
  currentUser: CurrentUser | null;
  project: ProjectResponse | null;
  setProject: Dispatch<SetStateAction<ProjectResponse | null>>;
  setProjectAccess: Dispatch<SetStateAction<"loading" | "granted" | "denied" | "error">>;
  canManageProjectPermissions: boolean;
};
