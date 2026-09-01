import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";

export type TranslationKey = keyof typeof zh;
const dictionaries: Record<"en" | "zh", Record<TranslationKey, string>> = { en, zh };

export type Locale = keyof typeof dictionaries;

export const supportedLocales: Array<{ code: Locale; htmlLang: string; label: string }> = [
  { code: "zh", htmlLang: "zh-Hant", label: "繁體中文" },
  { code: "en", htmlLang: "en", label: "English" }
];

export function isSupportedLocale(value: string | null): value is Locale {
  return supportedLocales.some((item) => item.code === value);
}

export function htmlLangForLocale(value: Locale) {
  return supportedLocales.find((item) => item.code === value)?.htmlLang ?? "zh-Hant";
}

export function t(key: TranslationKey, locale: Locale = "zh") {
  return dictionaries[locale][key] ?? dictionaries.zh[key] ?? key;
}

export function formatTranslation(key: TranslationKey, params: Record<string, string | number>, locale: Locale = "zh") {
  return Object.entries(params).reduce((message, [paramKey, value]) => message.replaceAll(`{${paramKey}}`, String(value)), t(key, locale));
}

function escapeRegularExpression(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function templateParameters(template: string, message: string): Record<string, string> | null {
  const names: string[] = [];
  const pieces = template.split(/(\{[A-Za-z0-9_]+\})/g);
  const pattern = pieces.map((piece) => {
    const match = piece.match(/^\{([A-Za-z0-9_]+)\}$/);
    if (!match) return escapeRegularExpression(piece);
    names.push(match[1]);
    return "(.+?)";
  }).join("");
  if (!names.length) return null;
  const match = message.match(new RegExp(`^${pattern}$`, "s"));
  if (!match) return null;
  return Object.fromEntries(names.map((name, index) => [name, match[index + 1]]));
}

function localizeKnownMessageAtDepth(message: string, locale: Locale, depth: number): string | null {
  const keys = Object.keys(dictionaries.zh) as TranslationKey[];
  for (const key of keys) {
    if (dictionaries.zh[key] === message || dictionaries.en[key] === message) return t(key, locale);
  }
  if (depth >= 4) return null;
  for (const key of keys) {
    for (const sourceLocale of ["zh", "en"] as const) {
      const params = templateParameters(dictionaries[sourceLocale][key], message);
      if (params) {
        const localizedParams = Object.fromEntries(
          Object.entries(params).map(([name, value]) => [name, localizeKnownMessageAtDepth(value, locale, depth + 1) ?? value]),
        );
        return formatTranslation(key, localizedParams, locale);
      }
    }
  }
  return null;
}

/** Re-resolve a previously formatted known UI message after a live locale switch. */
export function localizeKnownMessageOrNull(message: string, locale: Locale): string | null {
  return localizeKnownMessageAtDepth(message, locale, 0);
}

export function localizeKnownMessage(message: string, locale: Locale): string {
  return localizeKnownMessageOrNull(message, locale) ?? message;
}
