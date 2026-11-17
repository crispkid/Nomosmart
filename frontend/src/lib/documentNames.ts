import type { TranslationKey } from "@/lib/i18n";

type Translate = (key: TranslationKey) => string;
type Format = (key: TranslationKey, params: Record<string, string | number>) => string;

/** CHG-442 REN442-001: same limits as the backend `validate_title`. */
export const MAX_DOCUMENT_TITLE_LENGTH = 200;

/** CHG-442 REN442-004 details of `document_title_duplicate` (project name and owners are always present). */
export type DuplicateTitleDetails = {
  project_name: string | null;
  project_owners: string[];
  can_reference: boolean;
  project_id?: string;
  document_id?: string;
};

export function documentTitleProblem(raw: string): TranslationKey | null {
  const title = raw.normalize("NFC").trim();
  if (!title) return "documentTitleRequired";
  if (title.length > MAX_DOCUMENT_TITLE_LENGTH) return "documentTitleTooLong";
  if (/[\\/\u0000-\u001f\u007f]/.test(title) || !title.replace(/[ .]/g, "")) return "documentTitleInvalidCharacters";
  return null;
}

export function duplicateTitleDetails(details: unknown): DuplicateTitleDetails | null {
  if (!details || typeof details !== "object") return null;
  const value = details as Record<string, unknown>;
  if (!("project_owners" in value)) return null;
  return {
    project_name: typeof value.project_name === "string" ? value.project_name : null,
    project_owners: Array.isArray(value.project_owners) ? value.project_owners.filter((item): item is string => typeof item === "string") : [],
    can_reference: value.can_reference === true,
    project_id: typeof value.project_id === "string" ? value.project_id : undefined,
    document_id: typeof value.document_id === "string" ? value.document_id : undefined,
  };
}

/** One sentence naming the project and its owners, then what to do (reference it, or contact the owner). */
export function duplicateTitleMessage(details: DuplicateTitleDetails, t: Translate, format: Format): string {
  const owners = details.project_owners.length ? details.project_owners.join("、") : t("documentTitleDuplicateNoOwner");
  const where = format("documentTitleDuplicateWhere", { project: details.project_name ?? t("documentTitleDuplicateUnknownProject"), owners });
  return `${where} ${t(details.can_reference ? "documentTitleDuplicateUseReference" : "documentTitleDuplicateContactOwner")}`;
}

export function fileExtension(name: string | null | undefined): string {
  const match = /\.[^./\\]+$/.exec(name ?? "");
  return match ? match[0].toLowerCase() : "";
}
