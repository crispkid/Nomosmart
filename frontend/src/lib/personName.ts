import type { Locale } from "@/lib/i18n";

export type PersonNameFields = {
  given_name?: string | null;
  family_name?: string | null;
  display_name?: string | null;
};

function cleanNamePart(value: string | null | undefined) {
  return value?.trim() ?? "";
}

export function formatPersonName(person: PersonNameFields, locale: Locale) {
  const givenName = cleanNamePart(person.given_name);
  const familyName = cleanNamePart(person.family_name);
  if (givenName && familyName) return locale === "zh" ? `${familyName} ${givenName}` : `${givenName} ${familyName}`;
  return givenName || familyName || cleanNamePart(person.display_name);
}

export function personNameSearchText(person: PersonNameFields) {
  const givenName = cleanNamePart(person.given_name);
  const familyName = cleanNamePart(person.family_name);
  return [
    givenName,
    familyName,
    givenName && familyName ? `${givenName} ${familyName}` : "",
    givenName && familyName ? `${familyName} ${givenName}` : "",
    cleanNamePart(person.display_name)
  ].filter(Boolean).join(" ").toLowerCase();
}
