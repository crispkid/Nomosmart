export const systemTabIds = [
  "users",
  "roles",
  "permissions",
  "models",
  "prompts",
  "apiKeys",
  "identity",
  "status",
  "parameters"
] as const;

export type SystemTabId = (typeof systemTabIds)[number];
export type IdentityReauthResult = "pending" | "success" | "cancelled" | "error";

const systemTabIdSet = new Set<string>(systemTabIds);
const identityReauthResultSet = new Set<string>(["pending", "success", "cancelled", "error"]);

function singleSearchParam(value: string | string[] | null | undefined): string | null {
  return typeof value === "string" ? value : null;
}

export function parseSystemTab(value: string | string[] | null | undefined): SystemTabId {
  const candidate = singleSearchParam(value);
  return candidate && systemTabIdSet.has(candidate) ? candidate as SystemTabId : "users";
}

export function parseIdentityReauthResult(
  value: string | string[] | null | undefined
): IdentityReauthResult | null {
  const candidate = singleSearchParam(value);
  return candidate && identityReauthResultSet.has(candidate)
    ? candidate as IdentityReauthResult
    : null;
}

export function systemRouteUrl(
  currentUrl: string,
  tab: SystemTabId,
  reauth: IdentityReauthResult | null | undefined = undefined
): string {
  const url = new URL(currentUrl, "http://nomosmart.local");
  url.searchParams.set("tab", tab);
  if (reauth === null) url.searchParams.delete("reauth");
  if (reauth !== undefined && reauth !== null) url.searchParams.set("reauth", reauth);
  return `${url.pathname}${url.search}${url.hash}`;
}
