import type { RoleResponse, RoleUsersResponse, UserSummary } from "./api";

export type UserRow = { id: string; name: string; email: string; department: string; source: string; roles: string; status: string; raw?: UserSummary };
export type RoleRow = { id: string; name: string; members: number | null; manualMembers: number | null; ldapMembers: number | null; breakGlassMembers: number | null; groups: number | null; mappingGroupId: string | null; description: string | null; lockVersion: number; isSystem?: boolean; isActive?: boolean };

export function userRow(user: UserSummary): UserRow {
  return { id: user.id, name: user.display_name, email: user.email ?? "—", department: user.department ?? "—", source: user.auth_source, roles: (user.roles ?? []).map(role => role.name).join(", ") || "—", status: user.is_active ? "active" : "inactive", raw: user };
}

export function roleRow(role: RoleResponse, previous?: RoleRow): RoleRow {
  return { members: null, manualMembers: null, ldapMembers: null, breakGlassMembers: null, groups: null, mappingGroupId: null, ...previous, id: role.id, name: role.name, description: role.description, lockVersion: role.lock_version, isSystem: role.is_system, isActive: role.is_active };
}

export function roleMemberCounts(response: RoleUsersResponse) {
  return {
    members: new Set(response.users.map(user => user.user_id)).size,
    manualMembers: response.users.filter(user => user.source === "manual").length,
    ldapMembers: response.users.filter(user => user.source === "external_sync").length,
    breakGlassMembers: response.users.filter(user => user.source === "break_glass").length,
  };
}

export type SystemParameterValues = {
  uploadLimitMb: number;
  timezone: string;
  stagingTtlDays: number;
  sessionDraftTtlMinutes: number;
  ocrRequestOutputTokens: number | null;
  ocrDocumentOutputTokens: number | null;
};

export const defaultSystemParameters: SystemParameterValues = {
  uploadLimitMb: 100,
  timezone: "Asia/Taipei",
  stagingTtlDays: 14,
  sessionDraftTtlMinutes: 30,
  ocrRequestOutputTokens: null,
  ocrDocumentOutputTokens: null
};

export function validateSystemParameters(values: SystemParameterValues) {
  const errors: Partial<Record<keyof SystemParameterValues, string>> = {};

  if (!Number.isInteger(values.uploadLimitMb) || values.uploadLimitMb < 1 || values.uploadLimitMb > 10240) {
    errors.uploadLimitMb = "請輸入 1–10240 MB 的整數";
  }
  try {
    if (!values.timezone.trim()) throw new Error();
    new Intl.DateTimeFormat("en", { timeZone: values.timezone });
  } catch { errors.timezone = "請輸入有效的 IANA 時區，例如 Asia/Taipei"; }
  if (!Number.isInteger(values.stagingTtlDays) || values.stagingTtlDays < 1 || values.stagingTtlDays > 3650) {
    errors.stagingTtlDays = "請輸入 1–3650 天的整數";
  }
  if (!Number.isInteger(values.sessionDraftTtlMinutes) || (values.sessionDraftTtlMinutes !== 0 && (values.sessionDraftTtlMinutes < 5 || values.sessionDraftTtlMinutes > 120))) {
    errors.sessionDraftTtlMinutes = "請輸入 0 或 5–120 分鐘的整數";
  }

  if (values.ocrRequestOutputTokens == null || !Number.isInteger(values.ocrRequestOutputTokens) || values.ocrRequestOutputTokens < 1 || values.ocrRequestOutputTokens > 2147483647) errors.ocrRequestOutputTokens = "ocrTokenPositiveInteger";
  if (values.ocrDocumentOutputTokens == null || !Number.isInteger(values.ocrDocumentOutputTokens) || values.ocrDocumentOutputTokens < 1 || values.ocrDocumentOutputTokens > 2147483647) errors.ocrDocumentOutputTokens = "ocrTokenPositiveInteger";
  else if (values.ocrRequestOutputTokens != null && values.ocrDocumentOutputTokens < values.ocrRequestOutputTokens) errors.ocrDocumentOutputTokens = "ocrTokenDocumentTooSmall";
  return errors;
}

export function hasParameterErrors(errors: ReturnType<typeof validateSystemParameters>) {
  return Object.keys(errors).length > 0;
}

export type DirectorySyncScope = "people" | "groups" | "people_and_groups";
