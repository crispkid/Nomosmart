import type { RoleResponse, RoleUsersResponse, UserSummary } from "./api";

export type UserRow = { id: string; name: string; email: string; department: string; source: string; roles: string; status: string; raw?: UserSummary };
export type RoleRow = { id: string; name: string; members: number | null; manualMembers: number | null; ldapMembers: number | null; breakGlassMembers: number | null; groups: number | null; mappingGroupId: string | null; description: string | null; lockVersion: number; isSystem?: boolean; isActive?: boolean };

export function userRow(user: UserSummary): UserRow {
  return { id: user.id, name: user.display_name, email: user.email ?? "—", department: user.department ?? "—", source: user.auth_source, roles: user.knowledge_owner ? "Knowledge Owner" : "—", status: user.is_active ? "active" : "inactive", raw: user };
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
  ocrPageOutputTokens: number | null;
  ocrDocumentOutputTokens: number | null;
};

export const defaultSystemParameters: SystemParameterValues = {
  uploadLimitMb: 100,
  timezone: "Asia/Taipei",
  stagingTtlDays: 14,
  sessionDraftTtlMinutes: 30,
  ocrPageOutputTokens: null,
  ocrDocumentOutputTokens: null
};

export function validateSystemParameters(values: SystemParameterValues) {
  const errors: Partial<Record<keyof SystemParameterValues, string>> = {};

  if (!Number.isInteger(values.uploadLimitMb) || values.uploadLimitMb < 1 || values.uploadLimitMb > 1024) {
    errors.uploadLimitMb = "請輸入 1–1024 MB 的整數";
  }
  if (!/^[A-Za-z_]+\/[A-Za-z0-9_+\-]+$/.test(values.timezone)) {
    errors.timezone = "請輸入有效的 IANA 時區，例如 Asia/Taipei";
  }
  if (!Number.isInteger(values.stagingTtlDays) || values.stagingTtlDays < 1 || values.stagingTtlDays > 90) {
    errors.stagingTtlDays = "請輸入 1–90 天的整數";
  }
  if (!Number.isInteger(values.sessionDraftTtlMinutes) || (values.sessionDraftTtlMinutes !== 0 && (values.sessionDraftTtlMinutes < 5 || values.sessionDraftTtlMinutes > 120))) {
    errors.sessionDraftTtlMinutes = "請輸入 0 或 5–120 分鐘的整數";
  }

  if (values.ocrPageOutputTokens == null || !Number.isInteger(values.ocrPageOutputTokens) || values.ocrPageOutputTokens < 1 || values.ocrPageOutputTokens > 2147483647) errors.ocrPageOutputTokens = "ocrTokenPositiveInteger";
  if (values.ocrDocumentOutputTokens == null || !Number.isInteger(values.ocrDocumentOutputTokens) || values.ocrDocumentOutputTokens < 1 || values.ocrDocumentOutputTokens > 2147483647) errors.ocrDocumentOutputTokens = "ocrTokenPositiveInteger";
  else if (values.ocrPageOutputTokens != null && values.ocrDocumentOutputTokens < values.ocrPageOutputTokens) errors.ocrDocumentOutputTokens = "ocrTokenDocumentTooSmall";
  return errors;
}

export function hasParameterErrors(errors: ReturnType<typeof validateSystemParameters>) {
  return Object.keys(errors).length > 0;
}

export type DirectorySyncScope = "people" | "groups" | "people_and_groups";

export type IdentitySettings = {
  issuer: string;
  realm: string;
  clientId: string;
  audience: string;
  discoveryUrl: string;
  keycloakEnabled: boolean;
  syncEnabled: boolean;
  syncScope: DirectorySyncScope;
  schedule: string;
  timezone: string;
};

export type IdentityUnlockGrant = {
  userId: string;
  sessionId: string;
  scope: "identity-settings";
  issuedAt: number;
  expiresAt: number;
};

export const identityUnlockDurationMs = 10 * 60 * 1000;

export const emptyIdentitySettings: IdentitySettings = {
  issuer: "",
  realm: "",
  clientId: "",
  audience: "",
  discoveryUrl: "",
  keycloakEnabled: false,
  syncEnabled: false,
  syncScope: "people_and_groups",
  schedule: "",
  timezone: ""
};

export function validateIdentitySettings(values: IdentitySettings) {
  const errors: Partial<Record<keyof IdentitySettings, string>> = {};
  const validIdentityUrl = (value: string) => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "https:" || (parsed.protocol === "http:" && ["127.0.0.1", "localhost"].includes(parsed.hostname));
    } catch {
      return false;
    }
  };

  if (!validIdentityUrl(values.issuer)) errors.issuer = "Issuer 必須是 HTTPS URL";
  if (!values.realm.trim()) errors.realm = "Realm 為必填";
  if (!values.clientId.trim()) errors.clientId = "Client ID 為必填";
  if (!values.audience.trim()) errors.audience = "Audience 為必填";
  if (!validIdentityUrl(values.discoveryUrl)) errors.discoveryUrl = "Discovery URL 必須是 HTTPS URL";
  if (!/^\S+\s+\S+\s+\S+\s+\S+\s+\S+$/.test(values.schedule)) errors.schedule = "請輸入五欄 Cron 排程";
  if (!/^[A-Za-z_]+\/[A-Za-z0-9_+\-]+$/.test(values.timezone)) errors.timezone = "請輸入有效的 IANA 時區";
  return errors;
}

export function createIdentityUnlockGrant(userId: string, sessionId: string, now: number): IdentityUnlockGrant {
  return { userId, sessionId, scope: "identity-settings", issuedAt: now, expiresAt: now + identityUnlockDurationMs };
}

export function isIdentityUnlockValid(
  grant: IdentityUnlockGrant | null,
  context: { userId: string; sessionId: string; now: number; canEdit: boolean }
) {
  return Boolean(
    grant &&
    context.canEdit &&
    grant.scope === "identity-settings" &&
    grant.userId === context.userId &&
    grant.sessionId === context.sessionId &&
    context.now >= grant.issuedAt &&
    context.now < grant.expiresAt
  );
}
