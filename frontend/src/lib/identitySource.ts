import type { TranslationKey } from "./i18nClient";

// Historical values remain API identifiers. Only their presentation changes.
export function identitySourceLabel(source: string, t: (key: TranslationKey) => string): string {
  const keys: Record<string, TranslationKey> = {
    ldap: "identityOriginLdap", ad: "identityOriginAd", oidc: "identityOriginOidc",
    local: "identityOriginLocal", emergency: "identityOriginEmergency",
    keycloak: "identityOriginLegacy", keycloak_local: "identityOriginLegacyLocal"
  };
  return t(keys[source] ?? "identityOriginOther");
}
